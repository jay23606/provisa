# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1858, REQ-1996: the named demo ``weblogs`` works as shipped.

Its own docker-compose.yml brings the web shop up on ports of this test's own, under a compose
project of its own, with the log directories in a temporary directory; its seeder sends the shop
its fixed run of traffic. A real Provisa server (DuckDB engine, SQLite control plane) loads the
demo's config.yaml as is, with the environment start-ui-install.sh gives it: the demo directory
and the log directory allowed. Then every view of the demo is queried through ``/data/sql`` and
checked against the traffic the seeder reports it sent."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration]

_REPO = Path(__file__).resolve().parents[2]
_DEMO = _REPO / "demo" / "named" / "weblogs"
_ROLE = "org_admin"
#: The requests the seeder sends (demo/named/weblogs/seed.py REQUESTS).
_REQUESTS = 1500


class WeblogsStack:
    """The demo's compose stack, on leased ports, its logs and data under ``home``."""

    def __init__(self, home: Path) -> None:
        from tests.port_lease import lease_ports

        self.home = home
        self.pg_port, self.shop_port = lease_ports(2)
        self.project = f"weblogs-demo-{os.getpid()}"
        for sub in ("logs/nginx", "logs/postgres", "data"):
            (home / sub).mkdir(parents=True, exist_ok=True)

    @property
    def env(self) -> dict[str, str]:
        return {
            "PROVISA_NAMED_DEMO_DIR": str(self.home),
            "WEBLOGS_PG_PORT": str(self.pg_port),
            "WEBLOGS_SHOP_PORT": str(self.shop_port),
        }

    def _compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                self.project,
                "-f",
                str(_DEMO / "docker-compose.yml"),
                *args,
            ],
            env={**os.environ, **self.env},
            capture_output=True,
            text=True,
            check=check,
            timeout=900,
        )

    def up(self) -> None:
        """Bring the stack up and send its traffic: the seeder's exit is the run's end."""
        try:
            self._compose("up", "-d", "--build", "--wait", "postgres", "shop", "nginx")
            self._compose("up", "--exit-code-from", "seeder", "seeder")
        except subprocess.CalledProcessError as exc:
            logs = self._compose("logs", "--no-color", check=False).stdout
            raise AssertionError(
                f"the weblogs stack did not come up: {exc.stderr}\n{logs[-4000:]}"
            ) from exc

    def sent(self) -> dict[int, int]:
        """The statuses the seeder's requests were answered with, as it recorded them."""
        return {
            int(k): v for k, v in json.loads((self.home / "data" / ".seeded").read_text()).items()
        }

    def down(self) -> None:
        self._compose("down", "-v", "--remove-orphans", check=False)


def provisa_server(stack: WeblogsStack, org_id: str):
    """A Provisa server on the demo's own config.yaml, as start-ui-install.sh --demo weblogs
    starts it: the demo directory named and its logs/ allowed. Its data directory is the test's
    own, so the rows it lands start empty and go with the test."""
    from tests.integration.isolated_server import IsolatedServer

    return IsolatedServer(
        org_id,
        engine="duckdb",
        config=str(_DEMO / "config.yaml"),
        control_plane="sqlite",
        env={
            **stack.env,
            "PROVISA_LOGS_ALLOWED_ROOTS": str(stack.home / "logs"),
            "PROVISA_DATA_DIR": str(stack.home / "provisa"),
        },
    )


def query(server: Any, sql: str) -> list[dict[str, Any]]:
    resp = httpx.post(
        f"{server.base_url}/data/sql",
        json={"sql": sql, "role": _ROLE},
        headers={"X-Provisa-Role": _ROLE},
        timeout=180,
    )
    assert resp.status_code == 200, f"{sql}: HTTP {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "data" in body, f"{sql}: no data in {resp.text}"
    return body["data"]["sql"]


def await_logs_landed(server: Any, deadline_s: float = 300) -> None:
    """Wait until both logs are read in: every request the seeder sent is a row of the access
    log, and the database log has rows."""
    deadline = time.monotonic() + deadline_s
    seen: tuple[Any, Any] = (None, None)
    while time.monotonic() < deadline:
        access = query(server, 'SELECT COUNT(*) AS n FROM "shop"."access_log"')[0]["n"]
        db = query(server, 'SELECT COUNT(*) AS n FROM "shop"."db_log"')[0]["n"]
        seen = (access, db)
        if access == _REQUESTS and db > 0:
            return
        time.sleep(3)
    raise AssertionError(f"the logs never landed whole: access_log, db_log rows = {seen}")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    demo = WeblogsStack(tmp_path_factory.mktemp("weblogs"))
    try:
        demo.up()
        yield demo
    finally:
        demo.down()


@pytest.fixture(scope="module")
def server(stack):
    srv = provisa_server(stack, "weblogs_demo")
    srv.start(timeout=300)
    try:
        await_logs_landed(srv)
        yield srv
    except BaseException:
        print(srv.dump_stderr_debug()[-6000:])
        raise
    finally:
        srv.stop_process()


def test_every_request_is_a_row_of_the_access_log(stack, server):
    rows = query(server, 'SELECT status, COUNT(*) AS n FROM "shop"."access_log" GROUP BY status')
    assert {r["status"]: r["n"] for r in rows} == stack.sent()
    unread = query(
        server, 'SELECT COUNT(*) AS n FROM "shop"."access_log" WHERE "_parse_error" IS NOT NULL'
    )
    assert unread[0]["n"] == 0


def test_each_statement_names_the_request_it_served(server):
    rows = query(
        server,
        "SELECT COUNT(*) AS n, COUNT(a.request_id) AS matched, MIN(r.duration_ms) AS fastest "
        'FROM "shop"."view_request_sql" AS r '
        'LEFT JOIN "shop"."access_log" AS a ON a.request_id = r.request_id',
    )[0]
    assert rows["n"] > _REQUESTS  # every page runs at least one statement
    assert rows["matched"] == rows["n"]
    assert rows["fastest"] is not None and rows["fastest"] >= 0


def test_the_slowest_pages_are_the_report_and_the_ranked_search(server):
    rows = query(
        server,
        'SELECT path, page_ms, statements, slowest_sql_ms FROM "shop"."view_slowest_pages" '
        "ORDER BY page_ms DESC LIMIT 10",
    )
    assert len(rows) == 10
    assert {r["path"] for r in rows} <= {"/reports/top", "/search"}, rows
    assert all(r["statements"] >= 1 and r["slowest_sql_ms"] >= 100 for r in rows), rows


def test_each_server_error_is_a_request_whose_statement_failed(stack, server):
    rows = query(
        server,
        'SELECT path, status, state_code, statement FROM "shop"."view_requests_with_db_errors"',
    )
    assert len(rows) == stack.sent()[500]
    assert {r["status"] for r in rows} == {500}
    # The page whose column is gone, and an order beyond the stock or for no such customer.
    assert {r["state_code"] for r in rows} <= {"42703", "23514", "23503"}
    assert "42703" in {r["state_code"] for r in rows}
    assert all("/*" not in r["statement"] for r in rows)


def test_customers_served_errors_are_counted_with_their_orders(server):
    rows = query(
        server,
        'SELECT customer_id, server_errors, orders FROM "shop"."view_customers_with_5xx"',
    )
    served = query(
        server,
        'SELECT COUNT(*) AS n FROM "shop"."access_log" '
        "WHERE status >= 500 AND customer_id IS NOT NULL AND customer_id <= 200",
    )[0]["n"]
    assert rows and sum(r["server_errors"] for r in rows) == served
    assert any(r["orders"] for r in rows)


def test_viewed_products_no_order_includes(server):
    rows = query(server, 'SELECT product_id, views FROM "shop"."view_viewed_not_bought"')
    assert rows and all(r["views"] >= 1 for r in rows)
    ids = [r["product_id"] for r in rows]
    bought = query(
        server,
        'SELECT COUNT(*) AS n FROM "shop"."order_items" WHERE product_id IN '
        f"({', '.join(str(i) for i in ids)})",
    )[0]["n"]
    assert bought == 0
    # The products the generated orders never include, 81-120, are browsed in the traffic.
    assert any(83 <= i <= 120 for i in ids), ids


def test_slow_statements_are_grouped_by_table(server):
    rows = query(
        server,
        'SELECT table_name, statements, max_ms, p95_ms FROM "shop"."view_slow_statements_by_table"',
    )
    by_table = {r["table_name"]: r for r in rows}
    assert {"shop.products", "shop.orders", "shop.order_items", "shop.customers"} <= set(by_table)
    # The back office's report reads every order line and sleeps at least 200 ms.
    assert by_table["shop.order_items"]["max_ms"] >= 200
    assert all(float(r["p95_ms"]) <= float(r["max_ms"]) for r in rows)
