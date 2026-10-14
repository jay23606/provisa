-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The weblogs demo's shop database where the demo runs from its bundle (docker-compose.run.yml,
-- REQ-2049): the bundle's dump (dump/postgres.sql, written with no owners or grants) is loaded
-- first, and Provisa's reader is then given what db/init.sql gives it in the build.

CREATE ROLE provisa_reader LOGIN PASSWORD 'provisa_reader';
GRANT USAGE ON SCHEMA shop TO provisa_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO provisa_reader;
