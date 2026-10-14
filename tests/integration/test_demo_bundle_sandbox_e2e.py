# Copyright (c) 2026 Kenneth Stott
# Canary: db59ba60-c05d-4604-a1f1-851c1783ee89
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""E2E: the sandbox tier serves each demo's latest published bundle, with no redeploy (REQ-2049).

The ``test`` instance: a registry of this test's own (tests/integration/demo_registry.py) and a
sandbox tier told to pull the demo ``alpha`` from it (PROVISA_DEMO_BUNDLES). A bundle built and
published is what a visitor's sandbox reads; a newer one published while the tier runs is what
the next visitor's sandbox reads, while the sandbox opened before keeps its own. The demo's source
is deleted after each build: nothing the tier serves reads it."""

# Requirements: REQ-2049, REQ-2006

from __future__ import annotations

import sqlite3
import time

import httpx
import pytest

from tests.integration.test_demo_bundle_build_e2e import build, published_demo
from tests.integration.test_demo_sandboxes_e2e import _JWT_SECRET, _deployment_config

pytestmark = [pytest.mark.integration, pytest.mark.local_platform]

_ORG = "bundletiere2e"


@pytest.fixture(scope="module")
def registry():
    from tests.integration.demo_registry import DemoRegistry

    reg = DemoRegistry()
    reg.start()
    yield reg
    reg.stop()


def _publish(registry, named, out, commit: str, rows: list[str]) -> str:
    """Build alpha with ``rows``, publish it, and remove its source; the version published."""
    source = named / "alpha" / "animals.sqlite"
    db = sqlite3.connect(source)
    db.execute("DELETE FROM animals")
    db.executemany("INSERT INTO animals VALUES (?, ?)", list(enumerate(rows, start=1)))
    db.commit()
    db.close()
    bundle = build(named, "alpha", out, commit)
    registry.push(bundle)
    return bundle.name.removeprefix("alpha-").removesuffix(".tar.gz")


def _tier(work, registry):
    from tests.integration.isolated_server import IsolatedServer

    config = work / "config.yaml"
    _deployment_config(config)
    return IsolatedServer(
        _ORG,
        engine="duckdb",
        config=str(config),
        auth={"provider": "basic", "jwt_secret": _JWT_SECRET, "assignments_source": "provisa"},
        env={
            "PROVISA_SANDBOX_TIER": "true",
            "PROVISA_DEMO_BUNDLES": "alpha",
            "PROVISA_DEMO_REGISTRY": registry.url,
            "PROVISA_DATA_DIR": str(work / "data"),
        },
    )


def _open(tier) -> dict:
    deadline = time.monotonic() + 240
    while True:
        opened = httpx.post(f"{tier.base_url}/public/demos/alpha", timeout=300)
        if opened.status_code == 200:
            return opened.json()
        assert opened.json().get("code") == "sandbox.demo_not_ready", (
            opened.text,
            tier.dump_stderr_debug()[-6000:],
        )
        assert time.monotonic() < deadline, tier.dump_stderr_debug()[-6000:]
        time.sleep(2)


def _names(tier, sandbox: dict) -> list[str]:
    rows = httpx.post(
        f"{tier.base_url}/data/sql",
        json={"sql": "SELECT name FROM animals"},
        headers={"Authorization": f"Bearer {sandbox['token']}", "x-org-provisa": sandbox["org_id"]},
        timeout=120,
    )
    assert rows.status_code == 200, rows.text
    return sorted(r["name"] for r in rows.json()["data"]["sql"])


def test_a_new_sandbox_reads_the_latest_bundle_and_an_open_one_keeps_its_own(
    tmp_path_factory, registry
):
    work = tmp_path_factory.mktemp("bundle_tier")
    named = work / "named"
    published_demo(named, "alpha")
    first = _publish(registry, named, work / "out1", "a" * 40, ["ant", "ape"])
    (named / "alpha" / "animals.sqlite").unlink()

    tier = _tier(work, registry)
    tier.start(timeout=240)
    try:
        before = _open(tier)
        assert _names(tier, before) == ["ant", "ape"]
        assert (work / "data" / "demo-bundles" / "alpha" / "current").read_text().strip() == first

        published_demo(work / "named2", "alpha")
        second = _publish(registry, work / "named2", work / "out2", "b" * 40, ["asp", "auk", "ant"])
        (work / "named2" / "alpha" / "animals.sqlite").unlink()
        assert second != first

        after = _open(tier)
        assert _names(tier, after) == ["ant", "asp", "auk"]
        assert (work / "data" / "demo-bundles" / "alpha" / "current").read_text().strip() == second
        assert _names(tier, before) == ["ant", "ape"]  # opened before: its own copy
    finally:
        tier.stop_process()


def test_a_bundle_that_needs_a_newer_provisa_is_refused_by_name(tmp_path_factory, registry):
    work = tmp_path_factory.mktemp("bundle_newer")
    named = work / "named"
    published_demo(named, "alpha", requires="99.0.0")
    bundle = build(named, "alpha", work / "out", "c" * 40)
    registry.push(bundle)

    pulled = registry.pull("alpha", work / "demos")
    assert pulled.returncode == 2
    assert "needs Provisa 99.0.0 or newer; this is Provisa" in pulled.stderr
    assert not (work / "demos" / "alpha").exists() or not any((work / "demos" / "alpha").iterdir())
