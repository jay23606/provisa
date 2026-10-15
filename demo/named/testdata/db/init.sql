-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The testdata demo's production database (REQ-2053): a small shop -- customers, products, orders
-- and their lines -- loaded from the files generate.py writes beside this one. Every name and email
-- is generated; the demo's environments show it faked, prod shows it as it is.

CREATE TABLE customers (id integer PRIMARY KEY, name text NOT NULL, email text NOT NULL,
                        city text NOT NULL, region text NOT NULL, joined_on date NOT NULL);
CREATE TABLE products (id integer PRIMARY KEY, name text NOT NULL, category text NOT NULL,
                       price numeric(8, 2) NOT NULL, stock integer NOT NULL, description text NOT NULL);
CREATE TABLE orders (id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers,
                     placed_at timestamp NOT NULL, status text NOT NULL);
CREATE TABLE order_items (id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES orders,
                          product_id integer NOT NULL REFERENCES products, quantity integer NOT NULL,
                          unit_price numeric(8, 2) NOT NULL);

COPY customers FROM '/docker-entrypoint-initdb.d/data/customers.tsv';
COPY products FROM '/docker-entrypoint-initdb.d/data/products.tsv';
COPY orders FROM '/docker-entrypoint-initdb.d/data/orders.tsv';
COPY order_items FROM '/docker-entrypoint-initdb.d/data/order_items.tsv';
