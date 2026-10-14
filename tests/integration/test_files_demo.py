# Copyright (c) 2026 Kenneth Stott
# Canary: 488d2ac8-5ba9-455b-b841-ff8ffd94dd86
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-2032: the named demo ``files`` works as shipped.

A copy of the demo's directory is read by a real Provisa server (DuckDB engine, its own control
plane) loading the demo's config.yaml as is: one files source over drop/, every file a table, the
monthly complaint files one table over their glob. The answer's view is read live, built, read
again and read over REST; and the demo's example queries and its tour's statements answer rows.
"""

# Requirements: REQ-2032, REQ-788

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

pytestmark = [pytest.mark.integration]

_REPO = Path(__file__).resolve().parents[2]
_DEMO = _REPO / "demo" / "named" / "files"
_ROLE = "org_admin"
# What the committed data answers (generate.py, seed 2032).
_ANSWER = [
    ("Eastgate", 82, 23),
    ("Harbor Point", 75, 30),
    ("Riverside", 58, 20),
    ("Millbrook", 50, 10),
    ("Cedar Heights", 29, 5),
    ("Old Town", 26, 6),
]
_VIEW_SQL = (
    'SELECT neighborhood, complaints, active_permits FROM "city"."view_complaints_near_construction" '
    "ORDER BY complaints DESC"
)


@pytest.fixture(scope="module")
def home(tmp_path_factory) -> Path:
    """A copy of the demo's directory: the server writes its files' statistics beside them."""
    copy = tmp_path_factory.mktemp("files_demo") / "files"
    shutil.copytree(_DEMO, copy, ignore=shutil.ignore_patterns(".stats"))
    return copy


@pytest.fixture(scope="module")
def server(home, tmp_path_factory):
    from tests.integration.isolated_server import IsolatedServer

    data = tmp_path_factory.mktemp("files_demo_data")
    srv = IsolatedServer(
        "files_demo",
        engine="duckdb",
        config=str(home / "config.yaml"),
        control_plane="own",
        materialize_store_url=f"duckdb:///{data / 'store.duckdb'}",
        env={"PROVISA_NAMED_DEMO_DIR": str(home), "PROVISA_DATA_DIR": str(data / "provisa")},
    )
    srv.start(timeout=400)
    try:
        yield srv
    finally:
        srv.stop_process()


def _post(server, path: str, body: dict) -> httpx.Response:
    return httpx.post(
        f"{server.base_url}{path}", json=body, headers={"X-Provisa-Role": _ROLE}, timeout=300
    )


def query(server, sql: str) -> list[dict[str, Any]]:
    resp = _post(server, "/data/sql", {"sql": sql})
    assert resp.status_code == 200, f"{sql}: HTTP {resp.status_code}: {resp.text}"
    return resp.json()["data"]["sql"]


def _answer(rows: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    return [(r["neighborhood"], r["complaints"], r["active_permits"]) for r in rows]


@pytest.mark.parametrize("table", ["complaints", "permits", "budget", "inspections"])
def test_every_file_is_a_table(server, table):
    assert query(server, f'SELECT * FROM "city"."{table}" LIMIT 5')


def test_the_complaints_table_reads_every_monthly_file(server):
    rows = query(
        server,
        "SELECT SUBSTRING(opened_at, 1, 7) AS month, COUNT(*) AS complaints "
        'FROM "city"."complaints" GROUP BY 1 ORDER BY 1',
    )
    assert rows == [
        {"month": "2026-08", "complaints": 300},
        {"month": "2026-09", "complaints": 300},
    ]


def test_the_answer_is_the_same_live_and_built(server):
    assert _answer(query(server, _VIEW_SQL)) == _ANSWER
    resp = _post(
        server,
        "/admin/graphql",
        {
            "query": 'mutation { refreshMv(mvId: "view-view_complaints_near_construction") { success message } }'
        },
    )
    assert resp.json()["data"]["refreshMv"]["success"], resp.text
    assert _answer(query(server, _VIEW_SQL)) == _ANSWER


def test_the_answer_is_read_over_rest(server):
    resp = httpx.get(
        f"{server.base_url}/data/rest/city/view_complaints_near_construction",
        headers={"X-Provisa-Role": _ROLE},
        timeout=120,
    )
    assert resp.status_code == 200, resp.text
    rows = {r["neighborhood"]: (r["complaints"], r["activePermits"]) for r in resp.json()["data"]}
    assert rows == {name: (complaints, permits) for name, complaints, permits in _ANSWER}


@pytest.mark.parametrize(
    "path", sorted((_DEMO / "queries").glob("*.graphql")), ids=lambda p: p.stem
)
def test_each_example_query_answers_rows(server, path):
    resp = _post(server, "/data/graphql", {"query": path.read_text()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body.get("errors"), body
    [rows] = body["data"].values()
    assert rows, path.stem


_TOUR = yaml.safe_load((_DEMO / "tour.yaml").read_text())["steps"]


@pytest.mark.parametrize("step", [s for s in _TOUR if "sql" in s], ids=lambda s: s["key"])
def test_each_tour_statement_answers_rows(server, step):
    assert query(server, step["sql"]), step["key"]
