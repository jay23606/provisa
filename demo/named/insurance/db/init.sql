-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The insurance demo's private data: a property insurer's book of policies, by county. Generated,
-- and the same on every build: each value is derived from the policy's number, never random.
--
--   counties  the counties the insurer writes in, by their 5-digit FIPS code -- what joins the book
--             to FEMA's National Risk Index and the other county tables of govdata
--   policies  one row a policy in force: its county, line of business, total insured value (TIV),
--             annual premium and deductible

CREATE TABLE counties (
  county_fips varchar(5) PRIMARY KEY,
  county_name varchar NOT NULL,
  state_abbr  varchar(2) NOT NULL,
  -- How much of the book the county carries, relative to the others.
  weight      integer NOT NULL
);

INSERT INTO counties VALUES
  ('06037', 'Los Angeles', 'CA', 14), ('06073', 'San Diego', 'CA', 7),
  ('06059', 'Orange', 'CA', 7), ('06075', 'San Francisco', 'CA', 6),
  ('06001', 'Alameda', 'CA', 5), ('06067', 'Sacramento', 'CA', 4),
  ('06007', 'Butte', 'CA', 2), ('06097', 'Sonoma', 'CA', 3), ('06019', 'Fresno', 'CA', 3),
  ('12086', 'Miami-Dade', 'FL', 12), ('12011', 'Broward', 'FL', 8), ('12057', 'Hillsborough', 'FL', 6),
  ('12095', 'Orange', 'FL', 5), ('12071', 'Lee', 'FL', 4), ('12103', 'Pinellas', 'FL', 4),
  ('48201', 'Harris', 'TX', 11), ('48113', 'Dallas', 'TX', 7), ('48029', 'Bexar', 'TX', 5),
  ('48453', 'Travis', 'TX', 4), ('48167', 'Galveston', 'TX', 3),
  ('22071', 'Orleans', 'LA', 4), ('22033', 'East Baton Rouge', 'LA', 3),
  ('40109', 'Oklahoma', 'OK', 3), ('40143', 'Tulsa', 'OK', 3),
  ('08031', 'Denver', 'CO', 4), ('08041', 'El Paso', 'CO', 3),
  ('36061', 'New York', 'NY', 9), ('36047', 'Kings', 'NY', 6), ('17031', 'Cook', 'IL', 9),
  ('04013', 'Maricopa', 'AZ', 7), ('32003', 'Clark', 'NV', 5), ('53033', 'King', 'WA', 6),
  ('41051', 'Multnomah', 'OR', 3), ('13121', 'Fulton', 'GA', 4), ('37119', 'Mecklenburg', 'NC', 4),
  ('45019', 'Charleston', 'SC', 3), ('47157', 'Shelby', 'TN', 3), ('29095', 'Jackson', 'MO', 3),
  ('31055', 'Douglas', 'NE', 2), ('19169', 'Story', 'IA', 1), ('27053', 'Hennepin', 'MN', 4),
  ('55079', 'Milwaukee', 'WI', 3), ('26163', 'Wayne', 'MI', 4), ('39049', 'Franklin', 'OH', 4),
  ('42101', 'Philadelphia', 'PA', 5), ('25025', 'Suffolk', 'MA', 4), ('24510', 'Baltimore', 'MD', 3),
  ('51059', 'Fairfax', 'VA', 4);

CREATE TABLE policies (
  policy_id     integer PRIMARY KEY,
  county_fips   varchar(5) NOT NULL REFERENCES counties (county_fips),
  line          varchar NOT NULL,     -- homeowners | commercial_property | farmowners
  insured_value numeric(14, 2) NOT NULL,  -- total insured value (TIV), USD
  premium       numeric(12, 2) NOT NULL,  -- annual premium, USD
  deductible    numeric(12, 2) NOT NULL,  -- per-occurrence deductible, USD
  inception     date NOT NULL
);

-- Each policy lands in a county in proportion to the county's weight: policy n takes the county
-- whose running weight first passes n mod the total weight.
WITH weighted AS (
  SELECT county_fips,
         SUM(weight) OVER (ORDER BY county_fips) AS upto,
         SUM(weight) OVER () AS total
  FROM counties
),
numbered AS (
  SELECT n, abs(hashtext('policy:' || n)) AS h FROM generate_series(1, 6000) AS n
)
INSERT INTO policies
SELECT p.n,
       (SELECT w.county_fips FROM weighted w
        WHERE w.upto > (p.h % (SELECT MAX(total) FROM weighted)) ORDER BY w.upto LIMIT 1),
       CASE WHEN p.h % 10 < 7 THEN 'homeowners'
            WHEN p.h % 10 < 9 THEN 'commercial_property'
            ELSE 'farmowners' END,
       CASE WHEN p.h % 10 < 7 THEN 180000 + (p.h / 7) % 820000
            WHEN p.h % 10 < 9 THEN 750000 + (p.h / 7) % 9250000
            ELSE 400000 + (p.h / 7) % 2600000 END,
       0, 0,
       DATE '2024-01-01' + ((p.h / 13) % 730)::integer
FROM numbered p;

-- The premium is a rate on the insured value, the deductible a share of it.
UPDATE policies SET
  premium    = round(insured_value * CASE line WHEN 'homeowners' THEN 0.0042
                                           WHEN 'commercial_property' THEN 0.0031
                                           ELSE 0.0036 END, 2),
  deductible = round(insured_value * 0.01, -2);
