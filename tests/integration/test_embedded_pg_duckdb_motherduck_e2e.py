# Copyright (c) 2026 Kenneth Stott
# Canary: 3f61edbb-5818-4f6d-b657-84082a82ee0b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""E2E (REQ-1868, issue 254): a MotherDuck table read in place by the Postgres engine through
pg_duckdb, against MotherDuck itself.

pg_duckdb exposes MotherDuck tables through its sync worker, which creates each as a table in a
schema of its own naming some seconds after the engine is signed in -- not by importing a foreign
schema. The engine is an embedded Postgres from a private pginstall with the product's pg_duckdb
staged into it, as the embedded tier does (tests/embedded_pg.py; test_embedded_pg_duckdb_engine_e2e). Read-only: MotherDuck's sample_data database, which every
account holds; nothing is written to the account. Needs MOTHERDUCK_API_TOKEN (tests/env_creds
loads it locally; the warehouse lane's secret in CI)."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from provisa.core.models import SourceType

pytestmark = [pytest.mark.integration, pytest.mark.requires_warehouse]


@pytest.fixture(scope="module")
def engine_dsn():
    import psycopg

    from tests.embedded_pg import start_local_postgres

    pg = start_local_postgres(preload=("pg_duckdb",), fdws=True)
    try:
        with psycopg.connect(pg.dsn(), autocommit=True) as conn:
            conn.execute("CREATE EXTENSION pg_duckdb")
        yield pg.dsn()
    finally:
        pg.stop()


@pytest.fixture
def runtime(engine_dsn):
    from provisa.federation.pg_runtime import PgFederationRuntime

    rt = PgFederationRuntime(engine_dsn=engine_dsn)
    try:
        yield rt
    finally:
        rt.close()


def _motherduck(source_id: str, schema: str, table: str, token: str | None = None):
    return SimpleNamespace(
        id=source_id,
        catalog=source_id,
        type=SourceType.motherduck,
        host="",
        port=0,
        username="",
        password=token or os.environ["MOTHERDUCK_API_TOKEN"],
        database="sample_data",
        path=None,
        federation_hints={},
        mapping={},
        region=None,
        schema_name=schema,
        table_name=table,
    )


def test_the_pg_engine_reads_a_motherduck_table_pg_duckdb_synced(runtime):
    from provisa.compiler.naming import live_view_schema

    source = _motherduck("md-sample", "nyc", "taxi")
    runtime.attach_source(source)
    view = f'"{live_view_schema(source.catalog, source.schema_name)}"."taxi"'
    rows = runtime.run_sync(f"SELECT count(*) FROM {view}").rows
    assert rows[0][0] > 0
    # pg_duckdb's sync created the table in the schema of its naming, where the attach found it
    synced = runtime.run_sync("SELECT to_regclass('\"ddb$sample_data$nyc\".taxi') IS NOT NULL")
    assert synced.rows[0][0] is True


def test_another_table_of_the_database_is_read_on_the_same_sign_in(runtime):
    from provisa.compiler.naming import live_view_schema

    runtime.attach_source(_motherduck("md-sample", "nyc", "taxi"))
    movies = _motherduck("md-movies", "kaggle", "movies")
    runtime.attach_source(movies)
    view = f'"{live_view_schema(movies.catalog, movies.schema_name)}"."movies"'
    rows = runtime.run_sync(f"SELECT count(*) FROM {view}").rows
    assert rows[0][0] > 0


def test_a_second_motherduck_account_on_the_engine_is_refused_by_name(runtime):
    from provisa.federation.pg_motherduck import MotherDuckAttachError

    runtime.attach_source(_motherduck("md-sample", "nyc", "taxi"))
    other = _motherduck("md-other", "nyc", "taxi", token="not-the-same-account")
    with pytest.raises(MotherDuckAttachError, match="'md-other'.*another MotherDuck account"):
        runtime.attach_source(other)
