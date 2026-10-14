# Copyright (c) 2026 Kenneth Stott
# Canary: 52e958da-d94c-4e57-8dd2-740adfd924e6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A source whose server has gone fails nothing of another source's on DuckDB.

DuckDB reads every attached database for any catalog listing (``information_schema``,
``duckdb_columns()``). A PostgreSQL source left attached after its server went away failed every
later listing with "Unable to connect to Postgres": the replica copy's vector-index check listed
columns that way on every read of a landed table, so a deleted source failed the reads of every
other source's replicas.
"""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import psycopg
import pytest

from provisa.core.models import SourceType
from provisa.federation.duckdb_runtime import DuckDBFederationRuntime
from tests.embedded_pg import DATABASE, PASSWORD, ROLE, start_local_postgres


@pytest.fixture
def gone_source():
    """A runtime holding a live attach of a PostgreSQL source, whose server is then stopped."""
    pg = start_local_postgres()
    try:
        with psycopg.connect(pg.dsn(), autocommit=True) as conn:
            conn.execute("CREATE TABLE widgets (id INTEGER)")
        # A table of the source, as the attach walk hands it over (native_backend._attach_tbl).
        source = SimpleNamespace(
            id="e2e_postgresql_1",
            type=SourceType.postgresql,
            catalog="e2e_postgresql_1",
            host="127.0.0.1",
            port=pg.port,
            database=DATABASE,
            username=ROLE,
            password=PASSWORD,
            federation_hints={},
            mapping={},
            max_live_concurrency=None,
            schema_name="public",
            table_name="widgets",
        )
        runtime = DuckDBFederationRuntime()
        runtime.attach_source(source)
    finally:
        pg.stop()
    yield runtime, source
    runtime.close()


def _listing(runtime: DuckDBFederationRuntime) -> list:
    return runtime._con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'landed'"
    ).fetchall()


def test_a_dropped_sources_attach_is_let_go(gone_source):
    runtime, source = gone_source
    runtime._con.execute("CREATE TABLE landed (id INTEGER)")
    with pytest.raises(duckdb.IOException, match="Unable to connect to Postgres"):
        _listing(runtime)  # the reproducer: the dead attach fails an unrelated listing
    runtime.drop_source(source.id)
    assert _listing(runtime) == [("id",)]
    databases = runtime._con.execute("SELECT database_name FROM duckdb_databases()").fetchall()
    attached = {row[0] for row in databases}
    assert not {a for a in attached if source.id in a}


def test_a_replica_copy_indexes_its_vectors_with_a_dead_source_attached(gone_source):
    runtime = gone_source[0]
    cur = runtime._con.cursor()
    cur.execute("CREATE TABLE landed (id INTEGER, label VARCHAR)")
    runtime._index_replica_vectors(cur, "landed", "replicas__landed")  # no listing of every catalog
