# Copyright (c) 2026 Kenneth Stott
# Canary: c3f8a1d2-6b47-4e90-8a15-2f9d7c0b4e63
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""E2E: config-driven Postgres FDW connector drives a live attach (REQ-1177, PG SQL/MED branch).

The unit tests prove the descriptor emits standard SQL/MED DDL. This proves it DRIVES a real FDW: an
operator declares a `pgfdw_custom` source_type in config/custom_connectors.yaml (via
PROVISA_CUSTOM_CONNECTORS) pointing at the GENERIC pg_fdw descriptor, and PgFederationRuntime imports a
loopback Postgres schema through postgres_fdw and returns its rows — no engine code change.

This covers the IMPORT FOREIGN SCHEMA branch of the generic descriptor path (CREATE SERVER … FOREIGN
DATA WRAPPER + CREATE USER MAPPING + IMPORT FOREIGN SCHEMA) with postgres_fdw, a core contrib FDW the
embedded PG test stack already builds. The requirement's NAMED conformance target, mongo_fdw, is
federated LIVE against a real MongoDB — exercising the no-import / table-OPTIONS branch — in
tests/integration/test_custom_connectors_mongo_e2e.py.
"""

from __future__ import annotations

import textwrap
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.local_platform,
    pytest.mark.asyncio(loop_scope="session"),
]

asyncpg = pytest.importorskip("asyncpg")

from provisa.federation.pg_runtime import PgFederationRuntime  # noqa: E402
from tests.embedded_pg import start_local_postgres  # noqa: E402
from tests.integration.test_embedded_pg_fdw_engine_e2e import _loopback_source_params  # noqa: E402

_DESCRIPTOR = """
connectors:
  - engine: postgres
    source_type: pgfdw_custom
    kind: pg_fdw
    extension: postgres_fdw
    mechanism: attach_r
    supports_import: true
    server_options:
      host: "{host}"
      port: "{port}"
      dbname: "{database}"
    user_mapping:
      user: "{username}"
    remote_schema: "{schema}"
"""


@pytest.fixture(scope="session")
def pg_with_fdw():
    # An embedded PostgreSQL run from a private install with the product's FDW bundle staged.
    pg = start_local_postgres(fdws=True)
    yield pg
    pg.stop()


async def test_config_driven_pg_fdw_federates_postgres_source(pg_with_fdw, tmp_path, monkeypatch):
    server = pg_with_fdw
    dsn = server.dsn()

    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS demo_remote")
        await conn.execute("DROP TABLE IF EXISTS demo_remote.widgets")
        await conn.execute("CREATE TABLE demo_remote.widgets(id int, label text)")
        await conn.execute("INSERT INTO demo_remote.widgets VALUES (1,'a'),(2,'b'),(3,'c')")
    finally:
        await conn.close()

    cfg = tmp_path / "custom_connectors.yaml"
    cfg.write_text(textwrap.dedent(_DESCRIPTOR))
    monkeypatch.setenv("PROVISA_CUSTOM_CONNECTORS", str(cfg))

    lp = _loopback_source_params(server)
    rt = PgFederationRuntime(engine_dsn=dsn)
    try:
        # The descriptor made a brand-new source_type reachable on the PG engine — no code change.
        assert rt._engine.reachable("pgfdw_custom")

        src = SimpleNamespace(
            id="wid",
            catalog="wid",
            type=SimpleNamespace(value="pgfdw_custom"),
            host=lp["host"],
            port=lp["port"],
            database=lp["database"],
            username=lp["username"],
            password="",
            federation_hints={"schema": "demo_remote"},
            schema_name="inventory",
            table_name="widgets",
        )
        rt.attach_source(src)

        # REQ-1730: the engine exposes the source under the folded "{catalog}_{schema}" schema
        # the ENGINE route's physical SQL targets (source_to_catalog("wid") == "wid").
        res = rt.run_sync('SELECT "id", "label" FROM "wid_inventory"."widgets" ORDER BY "id"')
        assert res.column_names == ["id", "label"]
        assert [r[0] for r in res.rows] == [1, 2, 3]
        assert [r[1] for r in res.rows] == ["a", "b", "c"]
    finally:
        rt.close()
