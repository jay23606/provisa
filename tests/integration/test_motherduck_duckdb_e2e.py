# Copyright (c) 2026 Kenneth Stott
# Canary: 0e6044a7-d167-4ab1-8b4d-f4ffcf1f21a8
#
# This source code is licensed under the Business Source License 1.1
"""E2E (REQ-1998): MotherDuck read in place by the DuckDB engine, and a statement joining a local
DuckDB file with MotherDuck run as one DuckDB statement on the engine's connection (MotherDuck's
dual execution).

Read-only: MotherDuck's public sample_data share, attached by its share address; nothing is
written to the account. Skipped without MOTHERDUCK_API_TOKEN (tests/env_creds loads it)."""

from __future__ import annotations

import os
from types import SimpleNamespace

import duckdb
import pytest

from provisa.core.models import SourceType
from tests.env_creds import unset

pytestmark = [pytest.mark.integration, pytest.mark.requires_warehouse]
pytestmark.append(
    pytest.mark.skipif(
        not os.environ.get("MOTHERDUCK_API_TOKEN"),
        reason=f"not set: {unset('MOTHERDUCK_API_TOKEN')}",
    )
)

#: MotherDuck's public sample data, as its documentation names the share.
SAMPLE_DATA = "_share/sample_data/23b0d623-1361-421d-ae77-62d701d471e6"


def _source(source_id: str, type_: SourceType, **kw):
    return SimpleNamespace(
        id=source_id,
        type=type_,
        host="",
        port=0,
        username="",
        password="",
        database="",
        path=None,
        federation_hints={},
        mapping={},
        region=None,
        **kw,
    )


@pytest.fixture
def runtime():
    from provisa.federation.duckdb_runtime import DuckDBFederationRuntime

    rt = DuckDBFederationRuntime()
    try:
        yield rt
    finally:
        rt.close()


@pytest.fixture
def local_file(tmp_path):
    path = str(tmp_path / "local.duckdb")
    con = duckdb.connect(path)
    con.execute(
        "CREATE TABLE regions AS SELECT * FROM (VALUES (1, 'north'), (2, 'south')) t(id, name)"
    )
    con.close()
    return path


def _motherduck(table: str, schema: str):
    source = _source(
        "md-sample",
        SourceType.motherduck,
        schema_name=schema,
        table_name=table,
    )
    source.password = os.environ["MOTHERDUCK_API_TOKEN"]
    source.database = SAMPLE_DATA
    return source


def test_the_duckdb_engine_reads_a_motherduck_table_in_place(runtime):
    source = _motherduck("movies", "kaggle")
    runtime.attach_source(source)
    rows = list(runtime.run_sync(f"SELECT count(*) FROM {runtime._phys_name(source)}").rows)
    assert rows[0][0] > 0


def test_a_join_of_a_local_file_and_motherduck_is_one_statement_on_the_engine(runtime, local_file):
    md = _motherduck("movies", "kaggle")
    local = _source("local-regions", SourceType.duckdb, schema_name="main", table_name="regions")
    local.path = local_file
    runtime.attach_source(md)
    runtime.attach_source(local)
    sql = (
        f"SELECT r.name, count(*) FROM {runtime._phys_name(local)} r "
        f"CROSS JOIN (SELECT 1 FROM {runtime._phys_name(md)} LIMIT 3) m GROUP BY r.name ORDER BY 1"
    )
    rows = list(runtime.run_sync(sql).rows)
    assert rows == [("north", 3), ("south", 3)]
    plan = "\n".join(str(r[1]) for r in runtime._con.execute(f"EXPLAIN {sql}").fetchall())
    # MotherDuck plans the one statement: its operators carry where each part runs.
    assert "(L)" in plan and "(R)" in plan, plan
    # The local file is attached read-only (REQ-1997).
    with pytest.raises(duckdb.Error, match="read-only"):
        runtime._con.execute("INSERT INTO \"_src_local-regions\".main.regions VALUES (3, 'east')")


def test_a_second_motherduck_account_on_the_same_engine_is_refused_by_name(runtime):
    runtime.attach_source(_motherduck("movies", "kaggle"))
    other = _motherduck("taxi", "nyc")
    other.id = "md-other"
    other.password = "not-the-same-account"
    with pytest.raises(ValueError, match="'md-other'.*another MotherDuck account"):
        runtime.attach_source(other)
