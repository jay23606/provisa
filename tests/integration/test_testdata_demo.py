# Copyright (c) 2026 Kenneth Stott
# Canary: 2afe3bfa-4a17-4cee-942c-b036b99481cf
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-2053: the named demo ``testdata`` works as shipped.

Its own docker-compose.yml brings the shop's Postgres up on a port of this test's own, under a
compose project of its own, its production data loaded. A real Provisa server (DuckDB engine, its
own control plane) loads the demo's config.yaml as is, and scripts/run_demo_setup.py runs its
setup.yaml against it, as the launcher and the bundle build do: the two Test (fake) environments,
dev and test, are created. Then the same statements are read in prod and in each environment.
"""

# Requirements: REQ-2053

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

pytestmark = [pytest.mark.integration]

_REPO = Path(__file__).resolve().parents[2]
_DEMO = _REPO / "demo" / "named" / "testdata"
_CUSTOMERS = 'SELECT id, name, email, city FROM "shop"."customers" ORDER BY id'
_ORDERS_JOINED = (
    'SELECT COUNT(*) AS n FROM "shop"."orders" AS o JOIN "shop"."customers" AS c '
    "ON c.id = o.customer_id"
)


class TestdataStack:
    """The demo's database, on a leased port."""

    def __init__(self) -> None:
        from tests.port_lease import lease_ports

        (self.pg_port,) = lease_ports(1)
        self.project = f"testdata-demo-{os.getpid()}"

    @property
    def env(self) -> dict[str, str]:
        return {"TESTDATA_PG_PORT": str(self.pg_port)}

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
        try:
            self._compose("up", "-d", "--wait")
        except subprocess.CalledProcessError as exc:
            logs = self._compose("logs", "--no-color", check=False).stdout
            raise AssertionError(
                f"the testdata stack did not come up: {exc.stderr}\n{logs[-4000:]}"
            ) from exc

    def down(self) -> None:
        self._compose("down", "-v", "--remove-orphans", check=False)


@pytest.fixture(scope="module")
def stack():
    built = TestdataStack()
    built.up()
    try:
        yield built
    finally:
        built.down()


@pytest.fixture(scope="module")
def set_up(stack, tmp_path_factory):
    from tests.integration.isolated_server import IsolatedServer

    home = tmp_path_factory.mktemp("testdata_demo")
    srv = IsolatedServer(
        "testdata_demo",
        engine="duckdb",
        config=str(_DEMO / "config.yaml"),
        control_plane="own",
        materialize_store_url=f"duckdb:///{home / 'store.duckdb'}",
        env={**stack.env, "PROVISA_DATA_DIR": str(home / "provisa")},
    )
    srv.start(timeout=400)
    try:
        done = subprocess.run(
            [sys.executable, str(_REPO / "scripts" / "run_demo_setup.py"), str(_DEMO)]
            + ["--url", srv.base_url],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
        yield srv
    finally:
        srv.stop_process()


def _post(server, path: str, body: dict, env: str | None) -> httpx.Response:
    headers = {"X-Provisa-Role": "org_admin"}
    if env is not None:
        headers["x-provisa-env"] = env
    return httpx.post(f"{server.base_url}{path}", json=body, headers=headers, timeout=300)


def query(server, sql: str, env: str | None = None) -> list[dict[str, Any]]:
    resp = _post(server, "/data/sql", {"sql": sql}, env)
    assert resp.status_code == 200, f"{env} {sql}: HTTP {resp.status_code}: {resp.text}"
    return resp.json()["data"]["sql"]


def _real_customers() -> list[dict[str, Any]]:
    rows = (_DEMO / "db" / "customers.tsv").read_text().splitlines()
    return [
        dict(zip(("id", "name", "email", "city"), line.split("\t")[:4], strict=True))
        for line in rows
    ]


def test_prod_reads_the_real_rows(set_up):
    real = _real_customers()
    rows = query(set_up, _CUSTOMERS)
    assert [(str(r["id"]), r["name"], r["email"]) for r in rows] == [
        (c["id"], c["name"], c["email"]) for c in real
    ]


@pytest.mark.parametrize("env", ["dev", "test"])
def test_a_test_environment_reads_no_real_value(set_up, env):
    real = _real_customers()
    rows = query(set_up, _CUSTOMERS, env)
    assert len(rows) == len(real)
    for column in ("name", "email", "city"):
        shown = {r[column] for r in rows}
        assert not shown & {c[column] for c in real}, column
    assert all("@" in r["email"] for r in rows)


def test_dev_and_test_show_the_same_fakes(set_up):
    assert query(set_up, _CUSTOMERS, "dev") == query(set_up, _CUSTOMERS, "test")


@pytest.mark.parametrize("env", [None, "dev", "test"])
def test_keys_faked_alike_still_join(set_up, env):
    assert query(set_up, _ORDERS_JOINED, env) == [{"n": 120}]


def test_the_environments_are_test_fake_branches_of_the_model(set_up):
    me = httpx.get(f"{set_up.base_url}/auth/me", headers={"X-Provisa-Role": "org_admin"})
    org = me.json()["active_org_id"]
    listed = httpx.get(
        f"{set_up.base_url}/admin/orgs/{org}/environments",
        headers={"X-Provisa-Role": "org_admin"},
        timeout=60,
    ).json()["environments"]
    modes = {e["name"]: e["data_mode"] for e in listed}
    assert modes["dev"] == modes["test"] == "test_fake"


@pytest.mark.parametrize("env", [None, "dev"])
@pytest.mark.parametrize(
    "path", sorted((_DEMO / "queries").glob("*.graphql")), ids=lambda p: p.stem
)
def test_each_example_query_answers_rows(set_up, env, path):
    resp = _post(set_up, "/data/graphql", {"query": path.read_text()}, env)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body.get("errors"), body
    [rows] = body["data"].values()
    assert rows, path.stem


def test_each_tour_statement_answers_rows_in_its_environment(set_up):
    env = None
    for step in yaml.safe_load((_DEMO / "tour.yaml").read_text())["steps"]:
        if "env" in step:
            env = None if step["env"] == "prod" else step["env"]
        if "sql" in step:
            assert query(set_up, step["sql"], env), step["key"]
