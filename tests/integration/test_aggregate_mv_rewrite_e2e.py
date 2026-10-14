# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""E2E: an aggregate query is answered from a materialized view that pre-aggregates its table
(REQ-198, REQ-882).

A pg-engine server declares, in its file, a PostgreSQL table of orders and a view grouping it by
region and status with its sums and counts. Once the view is built, a GraphQL aggregate over the
table answers exactly as the same aggregate over the table itself does through /data/sql. A row
added at the source then shows which one answered: the SQL aggregate counts it, the GraphQL one
-- read from the view, built before the row -- does not.
"""

# Requirements: REQ-198, REQ-882

from __future__ import annotations

import tempfile
import time
from decimal import Decimal
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml

from tests.embedded_pg import DATABASE, PASSWORD, ROLE, start_local_postgres

pytestmark = [pytest.mark.integration]

_NAME = "aggregate_mv"
_ADMIN = "org_admin"
_ROWS = [("us", "open", 10), ("us", "open", 30), ("us", "shipped", 5), ("eu", "shipped", 7)]


def _config(pg) -> dict:
    return {
        "federation_engine": "pg",
        "auth": {
            "provider": "none",
            "assignments_source": "provisa",
            "default_assignments": [{"domain_id": "*", "role_id": _ADMIN}],
        },
        "naming": {"domain_prefix": False, "rules": []},
        "cache": {"enabled": False},
        "domains": [{"id": "shop", "description": "Shop"}],
        "roles": [],
        "sources": [
            {
                "id": "shop_pg",
                "type": "postgresql",
                "host": "127.0.0.1",
                "port": pg.port,
                "database": DATABASE,
                "username": ROLE,
                "password": PASSWORD,
                "replicate": -1,
            }
        ],
        "tables": [
            {
                "source_id": "shop_pg",
                "domain_id": "shop",
                "schema": "public",
                "table": "orders",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_primary_key": True,
                     "visible_to": [_ADMIN]},
                    {"name": "region", "data_type": "varchar", "visible_to": [_ADMIN]},
                    {"name": "status", "data_type": "varchar", "visible_to": [_ADMIN]},
                    {"name": "amount", "data_type": "integer", "visible_to": [_ADMIN]},
                ],
            }
        ],
        "materialized_views": [
            {
                "id": "orders_rollup",
                "refresh_interval": 3600,
                "sql": (
                    "SELECT region, status, SUM(amount) AS total, COUNT(*) AS n "
                    "FROM orders GROUP BY region, status"
                ),
            }
        ],
    }  # fmt: skip


@pytest.fixture
def source_pg():
    pg = start_local_postgres()
    try:
        with psycopg.connect(pg.dsn(), autocommit=True) as conn:
            conn.execute(
                "CREATE TABLE orders (id serial PRIMARY KEY, region text, status text, amount int)"
            )
            for row in _ROWS:
                conn.execute("INSERT INTO orders (region, status, amount) VALUES (%s, %s, %s)", row)
        yield pg
    finally:
        pg.stop()


@pytest.fixture
def server(source_pg):
    from tests.integration.isolated_server import IsolatedServer

    store = start_local_postgres()
    try:
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / "config.yaml"
            path.write_text(yaml.safe_dump(_config(source_pg)))
            srv = IsolatedServer(
                _NAME,
                engine="pg",
                config=str(path),
                control_plane="own",
                env={"PROVISA_MATERIALIZE_URL": store.dsn()},
            )
            try:
                srv.start()
                yield srv
            finally:
                srv.stop_process()
    finally:
        store.stop()


def _post(srv, path: str, body: dict) -> dict:
    response = httpx.post(
        f"{srv.base_url}{path}", json=body, headers={"X-Provisa-Role": _ADMIN}, timeout=120
    )
    assert response.status_code == 200, f"{response.text}\n{srv.dump_stderr_debug()[-6000:]}"
    payload = response.json()
    assert "errors" not in payload, payload
    return payload


def _built(srv) -> bool:
    views = _post(srv, "/admin/graphql", {"query": "{ mvList { id status lastError } }"})
    (view,) = [v for v in views["data"]["mvList"] if v["id"] == "orders_rollup"]
    assert view["lastError"] is None, view
    return view["status"] == "fresh"


def _graphql(srv) -> dict[str, tuple[int, Decimal]]:
    """Orders counted and summed by region, through GraphQL: the compiled path."""
    data = _post(
        srv,
        "/data/graphql",
        {
            "query": "{ orders_group_by(by: [region]) { groupKey "
            "aggregate { count sum { amount } } } }"
        },
    )["data"]["orders_group_by"]
    return {
        g["groupKey"]["region"]: (
            int(g["aggregate"]["count"]),
            Decimal(str(g["aggregate"]["sum"]["amount"])),
        )
        for g in data
    }


def _sql(srv) -> dict[str, tuple[int, Decimal]]:
    """The same, through /data/sql over the table."""
    payload = _post(
        srv,
        "/data/sql",
        {
            "sql": "SELECT region, COUNT(*) AS n, SUM(amount) AS total FROM orders GROUP BY region",
            "role": _ADMIN,
        },
    )
    rows = payload.get("data") or payload.get("rows") or []
    if isinstance(rows, dict):
        rows = next(iter(rows.values()))
    return {r["region"]: (int(r["n"]), Decimal(str(r["total"]))) for r in rows}


def test_an_aggregate_is_answered_from_the_view_and_as_the_table_answers(server, source_pg):
    deadline = time.monotonic() + 120
    while not _built(server):
        assert time.monotonic() < deadline, server.dump_stderr_debug()[-6000:]
        time.sleep(1)

    expected = {"us": (3, Decimal(45)), "eu": (1, Decimal(7))}
    assert _sql(server) == expected
    assert _graphql(server) == expected

    with psycopg.connect(source_pg.dsn(), autocommit=True) as conn:
        conn.execute("INSERT INTO orders (region, status, amount) VALUES ('eu', 'open', 100)")
    assert _sql(server)["eu"] == (2, Decimal(107))  # the table has the row
    assert _graphql(server) == expected  # the view, built before it, does not
