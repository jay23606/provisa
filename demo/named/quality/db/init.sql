-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The quality demo's database (REQ-2051): a chain of five shops' sales feed and bronze, where it
-- lands. Silver, the results of its checks and gold are Provisa's materialized views over bronze
-- (config.yaml); they are not here.
--
--   store     the chain's shops
--   incoming  the feed as delivered, a batch a day (db/incoming.tsv)
--   bronze    every batch landed, append-only: the well-formed fields typed on landing, the messy
--             ones (shop code, product, price) kept as the feed spelled them, every row stamped
--             with its batch and when it landed
--
-- sales.land_batch(n) lands batch n of the feed into bronze, once: what the seeder runs.

CREATE ROLE provisa LOGIN PASSWORD 'provisa';
CREATE SCHEMA sales AUTHORIZATION provisa;
SET search_path = sales;

CREATE TABLE store (
    store_id text PRIMARY KEY,
    name text NOT NULL,
    region text NOT NULL
);
INSERT INTO store VALUES
    ('S-01', 'Harbour Street', 'North'),
    ('S-02', 'Station Square', 'North'),
    ('S-03', 'Market Hall', 'South'),
    ('S-04', 'Riverside', 'South'),
    ('S-05', 'Airport', 'East');

CREATE TABLE incoming (
    line_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id integer NOT NULL,
    sale_id text,
    store text,
    product text,
    sold_at text,
    quantity text,
    unit_price text
);
COPY incoming (batch_id, sale_id, store, product, sold_at, quantity, unit_price)
    FROM '/docker-entrypoint-initdb.d/incoming.tsv';

CREATE TABLE bronze (
    line_id integer PRIMARY KEY,
    batch_id integer NOT NULL,
    landed_at timestamptz NOT NULL,
    sale_id text NOT NULL,
    sold_at timestamp NOT NULL,
    quantity integer NOT NULL,
    store text,
    product text,
    unit_price text
);

CREATE FUNCTION land_batch(batch integer) RETURNS integer AS $$
    WITH landed AS (
        INSERT INTO sales.bronze
            (line_id, batch_id, landed_at, sale_id, sold_at, quantity, store, product, unit_price)
        SELECT line_id, batch_id, now(), sale_id, sold_at::timestamp, quantity::integer, store,
               product, unit_price
        FROM sales.incoming
        WHERE batch_id = batch
          AND NOT EXISTS (SELECT 1 FROM sales.bronze b WHERE b.batch_id = batch)
        RETURNING 1
    )
    SELECT count(*)::integer FROM landed;
$$ LANGUAGE sql;

ALTER TABLE store OWNER TO provisa;
ALTER TABLE incoming OWNER TO provisa;
ALTER TABLE bronze OWNER TO provisa;
ALTER FUNCTION land_batch(integer) OWNER TO provisa;
