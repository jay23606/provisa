-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The weblogs demo's shop database (REQ-1858, REQ-1996): customers, products and their orders,
-- generated from a fixed seed so every start holds the same rows. Two roles: `shop`, the app,
-- whose every statement the server logs with its duration; `provisa_reader`, Provisa, whose
-- statements it does not, so the database log holds the shop's traffic and nothing else.

CREATE ROLE shop LOGIN PASSWORD 'shop';
CREATE ROLE provisa_reader LOGIN PASSWORD 'provisa_reader';
ALTER ROLE shop SET log_min_duration_statement = 0;
ALTER ROLE provisa_reader SET log_min_duration_statement = -1;

CREATE SCHEMA shop AUTHORIZATION shop;
SET search_path = shop;

CREATE TABLE customers (
    id integer PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL UNIQUE,
    city text NOT NULL,
    joined_on date NOT NULL
);

CREATE TABLE products (
    id integer PRIMARY KEY,
    name text NOT NULL,
    category text NOT NULL,
    price numeric(10, 2) NOT NULL,
    stock integer NOT NULL CHECK (stock >= 0),
    description text NOT NULL
);

CREATE TABLE orders (
    id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers (id),
    placed_at timestamp NOT NULL,
    status text NOT NULL
);

CREATE TABLE order_items (
    id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES orders (id),
    product_id integer NOT NULL REFERENCES products (id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(10, 2) NOT NULL
);

-- New orders the shop takes during the demo continue after the generated ones.
CREATE SEQUENCE orders_id_seq START 1001 OWNED BY orders.id;
CREATE SEQUENCE order_items_id_seq START 5001 OWNED BY order_items.id;

SELECT setseed(0.1858);

INSERT INTO customers
SELECT i,
       (ARRAY['Ada', 'Ben', 'Chloe', 'Dev', 'Elena', 'Femi', 'Grace', 'Hiro', 'Ines', 'Jonas',
              'Kemi', 'Liam', 'Mara', 'Noor', 'Omar', 'Priya', 'Quinn', 'Rosa', 'Sven', 'Tara'])
           [1 + (i % 20)]
       || ' ' ||
       (ARRAY['Adams', 'Baker', 'Costa', 'Diaz', 'Evans', 'Fischer', 'Garcia', 'Haddad', 'Ito',
              'Jensen', 'Kowalski', 'Lopez', 'Moreau', 'Nakamura', 'Okafor'])[1 + (i * 7 % 15)],
       'customer' || i || '@example.com',
       (ARRAY['Leeds', 'Lyon', 'Porto', 'Osaka', 'Austin', 'Accra', 'Pune', 'Bergen'])[1 + (i % 8)],
       date '2024-01-01' + (random() * 600)::int
FROM generate_series(1, 200) AS i;

INSERT INTO products
SELECT i,
       (ARRAY['Trail', 'City', 'Studio', 'Harbor', 'Summit', 'Meadow'])[1 + (i % 6)] || ' '
       || (ARRAY['Backpack', 'Lamp', 'Kettle', 'Jacket', 'Mug', 'Notebook', 'Chair', 'Speaker'])
           [1 + (i % 8)] || ' ' || i,
       (ARRAY['outdoor', 'home', 'kitchen', 'apparel', 'office', 'audio'])[1 + (i % 6)],
       round((5 + random() * 245)::numeric, 2),
       (random() * 40)::int,
       'A ' || (ARRAY['sturdy', 'light', 'classic', 'compact', 'bright'])[1 + (i % 5)]
       || ' piece for everyday use, item ' || i
FROM generate_series(1, 120) AS i;

INSERT INTO orders
SELECT i,
       1 + (random() * 199)::int,
       timestamp '2025-01-01' + random() * interval '270 days',
       (ARRAY['placed', 'paid', 'shipped', 'delivered', 'delivered', 'cancelled'])
           [1 + (random() * 5)::int]
FROM generate_series(1, 1000) AS i;

-- Products 1-80 sell; 81-120 are browsed in the demo's traffic but never bought.
INSERT INTO order_items
SELECT i,
       1 + ((i - 1) / 4),
       1 + (random() * 79)::int,
       1 + (random() * 3)::int,
       0
FROM generate_series(1, 4000) AS i;
UPDATE order_items AS oi SET unit_price = p.price FROM products AS p WHERE p.id = oi.product_id;

ALTER TABLE customers OWNER TO shop;
ALTER TABLE products OWNER TO shop;
ALTER TABLE orders OWNER TO shop;
ALTER TABLE order_items OWNER TO shop;
ALTER SEQUENCE orders_id_seq OWNER TO shop;
ALTER SEQUENCE order_items_id_seq OWNER TO shop;
GRANT USAGE ON SCHEMA shop TO provisa_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO provisa_reader;
