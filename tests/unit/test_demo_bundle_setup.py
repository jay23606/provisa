# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-2016, REQ-2049: a demo with a setup.yaml is set up in its bundle build, with the extras it
names installed, and its Qdrant stores are carried as snapshots its run-time compose recovers; a
bundled demo is not set up again where it runs."""

# Requirements: REQ-2016, REQ-2049

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SONNETS = _REPO / "demo" / "named" / "sonnets"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "demo_bundle", _REPO / "scripts" / "demo_bundle.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _builder()


def test_a_qdrant_store_is_saved_as_one_snapshot_a_collection(tmp_path, monkeypatch):
    demo = tmp_path / "sonnets"
    demo.mkdir()
    (demo / "docker-compose.yml").write_text("services: {}\n")
    stores = builder.Stores(demo)
    config = {
        "services": {
            "qdrant": {
                "image": "qdrant/qdrant:v1.12.4",
                "labels": {"com.provisa.demo.role": "vector"},
            }
        }
    }

    def _compose(*args, **_kw):
        if args[0] == "config":
            return type("Done", (), {"stdout": json.dumps(config)})()
        assert args == ("port", "qdrant", "6333")
        return type("Done", (), {"stdout": "0.0.0.0:41234\n"})()

    asked: list[str] = []

    def _get(url, **_kw):
        asked.append(f"GET {url}")
        body = {"result": {"collections": [{"name": "sonnet_lines"}]}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    def _post(url, **_kw):
        asked.append(f"POST {url}")
        body = {"result": {"name": "sonnet_lines-1.snapshot"}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    @contextlib.contextmanager
    def _stream(method, url, **_kw):
        asked.append(f"{method} {url}")
        yield httpx.Response(200, content=b"snapshot bytes", request=httpx.Request(method, url))

    monkeypatch.setattr(stores, "_compose", _compose)
    monkeypatch.setattr(builder.httpx, "get", _get)
    monkeypatch.setattr(builder.httpx, "post", _post)
    monkeypatch.setattr(builder.httpx, "stream", _stream)

    assert stores.dump() == ["qdrant/sonnet_lines"]
    assert (demo / "dump" / "qdrant" / "sonnet_lines.snapshot").read_bytes() == b"snapshot bytes"
    assert asked == [
        "GET http://127.0.0.1:41234/collections",
        "POST http://127.0.0.1:41234/collections/sonnet_lines/snapshots",
        "GET http://127.0.0.1:41234/collections/sonnet_lines/snapshots/sonnet_lines-1.snapshot",
    ]


@pytest.mark.parametrize("has_setup", [True, False], ids=["setup", "no-setup"])
def test_a_demo_s_setup_runs_after_its_stores_come_up_and_before_its_seed(
    tmp_path, monkeypatch, has_setup
):
    named = tmp_path / "named"
    demo = named / "sonnets"
    demo.mkdir(parents=True)
    (demo / "demo.yaml").write_text("published: true\nrequires_provisa: 0.1.0a483\n")
    if has_setup:
        (demo / "setup.yaml").write_text("steps: []\n")
    done: list[str] = []
    monkeypatch.setattr(builder.Stores, "up", lambda self: done.append("up"))
    monkeypatch.setattr(builder.Stores, "dump", lambda self: done.append("dump") or [])
    monkeypatch.setattr(builder.Stores, "down", lambda self: done.append("down"))
    monkeypatch.setattr(builder, "_set_up", lambda *_a: done.append("set up"))
    monkeypatch.setattr(builder, "_seed", lambda *_a: done.append("seed"))
    monkeypatch.setattr(builder.bundles, "pack", lambda _demo, _manifest: b"bundle")
    args = argparse.Namespace(
        name="sonnets", named_dir=named, out=tmp_path / "out", commit="a" * 40, timeout=60.0
    )
    assert builder.build(args) == 0
    expected = (
        ["up", "set up", "seed", "dump", "down"] if has_setup else ["up", "seed", "dump", "down"]
    )
    assert done == expected


def test_the_bundle_action_installs_a_demo_s_extras_before_it_builds():
    action = yaml.safe_load(
        (_REPO / ".github" / "actions" / "demo-bundle" / "action.yml").read_text()
    )
    names = [step["name"] for step in action["runs"]["steps"]]
    assert names.index("Install the demo's extras") < names.index("Build the bundle")
    install = action["runs"]["steps"][names.index("Install the demo's extras")]["run"]
    assert "scripts/demo_extras.py" in install
    assert "https://download.pytorch.org/whl/cpu torch" in install


def test_a_bundled_demo_is_not_set_up_again_where_it_runs():
    launcher = (_REPO / "start-ui-install.sh").read_text()
    guard = launcher[: launcher.index("scripts/run_demo_setup.py")].rsplit("\nif ", 1)[1]
    assert '"$_DEMO_BUNDLED" = false' in guard
    assert '"$_NAMED_DIR/setup.yaml"' in guard


def test_the_sonnets_run_time_compose_loads_what_its_build_saves():
    run = yaml.safe_load((_SONNETS / "docker-compose.run.yml").read_text())
    postgres, qdrant = run["services"]["postgres"], run["services"]["qdrant"]
    assert (
        "./dump/postgres.sql:/docker-entrypoint-initdb.d/10-sonnets.sql:ro" in postgres["volumes"]
    )
    assert "./dump/qdrant:/snapshots:ro" in qdrant["volumes"]
    # Recovered at start from the snapshot the build saved, dump/<service>/<collection>.snapshot.
    assert qdrant["command"] == [
        "./qdrant",
        "--snapshot",
        "/snapshots/sonnet_lines.snapshot:sonnet_lines",
    ]
    built = yaml.safe_load((_SONNETS / "docker-compose.yml").read_text())
    assert built["services"]["qdrant"]["image"] == qdrant["image"]
    assert built["services"]["qdrant"]["labels"]["com.provisa.demo.role"] == "vector"
