# Copyright (c) 2026 Kenneth Stott
# Canary: 690dd498-1a19-41c7-aa12-8ac0fb7d10db
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Prod and a Test (synthetic) environment never read each other's rows, on each engine that
generates synthetic rows (REQ-1942, REQ-1529).

Every environment of an org shares one engine. DuckDB names each environment's catalogs for the
environment; Trino's catalogs are fixed names, which is the case this file exists for. The same
scenario as ``test_synthetic_dataset_e2e.py``'s isolation test, on a server per engine: a real
table of three regions, an environment generated from a declared profile of one region that is
no real row's, and the two read in both orders, before and after the environment's runtime is
built anew.
"""

# Requirements: REQ-1942, REQ-1529

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.test_join_pattern_refresh_e2e import _pg
from tests.integration.test_synthetic_dataset_e2e import _call, _generate_whole_model, _sql

pytestmark = [pytest.mark.requires_trino, pytest.mark.integration]

pytest.importorskip("duckdb")

_ORG = "syn_iso_e2e"
_CONFIG = "tests/fixtures/synthetic_isolation_config.yaml"
_SCHEMA = "syn_iso_e2e"
_REAL = ["east", "north", "west"]


async def _seed() -> None:
    conn = await _pg()
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        await conn.execute(f"CREATE SCHEMA {_SCHEMA}")
        await conn.execute(f"CREATE TABLE {_SCHEMA}.syn_orders (id int PRIMARY KEY, region text)")
        await conn.executemany(
            f"INSERT INTO {_SCHEMA}.syn_orders VALUES ($1, $2)",
            [(1, "east"), (2, "west"), (3, "north")],
        )
    finally:
        await conn.close()


async def _drop() -> None:
    conn = await _pg()
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    finally:
        await conn.close()


@pytest.fixture(scope="module", params=["duckdb", "trino"])
def server(request):
    """A server on ``request.param``, as the helpers of the synthetic suite address one."""
    from tests.integration.isolated_server import IsolatedServer, drop_org_schema

    asyncio.run(_seed())
    store_dir = tempfile.TemporaryDirectory()
    org = f"{_ORG}_{request.param}"
    if request.param == "duckdb":
        # An environment is a schema of the control plane, so the plane is Postgres on both.
        srv = IsolatedServer(
            org,
            engine="duckdb",
            config=_CONFIG,
            materialize_store_url=f"duckdb:///{Path(store_dir.name) / 'materialize.duckdb'}",
        )
    else:
        srv = IsolatedServer(org, engine="trino", config=_CONFIG)
    srv.start()
    try:
        yield SimpleNamespace(
            ports={"http": srv.http_port},
            org_id=srv.org_id,
            log_text=srv.dump_stderr_debug,
            engine=request.param,
        )
    finally:
        srv.stop_process()
        store_dir.cleanup()
        asyncio.run(drop_org_schema(org))
        asyncio.run(_drop())


def test_prod_and_a_synthetic_environment_never_read_each_others_rows(server):
    boot = server
    base = f"/admin/orgs/{boot.org_id}/environments"
    regions = "SELECT region FROM syn_orders"

    status, rows = _sql(boot, regions)
    assert status == 200 and sorted(r["region"] for r in rows) == _REAL, (boot.engine, rows)

    status, body = _call(boot, "POST", base, {"name": "isolated", "data_mode": "test_synthetic"})
    assert status == 200, (boot.engine, body)
    status, plan = _call(boot, "GET", f"{base}/isolated/synthetic/plan")
    assert status == 200, (boot.engine, plan)
    orders = next(t for t in plan["tables"] if t["tableName"] == "syn_orders")
    status, body = _call(
        boot,
        "POST",
        f"/admin/tables/{orders['tableId']}/declared-profiles",
        {
            "profile": {
                "rowCount": 12,
                "columns": {
                    "id": {"nullShare": 0, "distinctCount": 12, "range": {"min": 1, "max": 12}},
                    "region": {"nullShare": 0, "values": [{"value": "mars", "weight": 1}]},
                },
            }
        },
        env="isolated",
    )
    assert status == 200, (boot.engine, body)
    _generate_whole_model(boot, "isolated", {"seed": 4, "scale": 1})

    def prod() -> None:
        status, rows = _sql(boot, regions)
        assert status == 200 and sorted(r["region"] for r in rows) == _REAL, (
            boot.engine,
            "prod",
            rows,
        )

    def synthetic() -> None:
        status, rows = _sql(boot, regions, env="isolated")
        assert status == 200 and [r["region"] for r in rows] == ["mars"] * 12, (
            boot.engine,
            "isolated",
            rows,
        )

    # Both orders, the environment's runtime the last one built.
    synthetic(), prod(), synthetic(), prod()
    # The environment builds its runtime anew (its sources are attached again).
    status, body = _call(boot, "POST", f"{base}/isolated/mutations/reset")
    assert status == 200 and body["refreshed"] in ("rebuilt", "uncached"), (boot.engine, body)
    synthetic(), prod(), synthetic()
    # prod builds its schemas anew, after the environment.
    status, body = _call(
        boot,
        "POST",
        "/admin/actions/webhooks",
        {"name": "isolation_probe", "url": "http://127.0.0.1:9/never", "domainId": "syniso"},
    )
    assert status == 200, (boot.engine, body)
    prod(), synthetic(), prod()
    # And the environment once more, after prod.
    status, body = _call(boot, "POST", f"{base}/isolated/mutations/reset")
    assert status == 200, (boot.engine, body)
    prod(), synthetic(), prod(), synthetic()
