-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The insider demo where it runs from its bundle (docker-compose.run.yml): the role Provisa reads
-- it as, given the database the bundle's dump loaded just before. Read only: the database is shared
-- by every sandbox of the demo.
CREATE ROLE provisa LOGIN PASSWORD 'provisa';
GRANT USAGE ON SCHEMA bank TO provisa;
GRANT SELECT ON ALL TABLES IN SCHEMA bank TO provisa;
