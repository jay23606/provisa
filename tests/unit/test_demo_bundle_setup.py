# Copyright (c) 2026 Kenneth Stott
# Canary: 69648c50-bdc7-427d-b52c-9d5708a9ebf8
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


@pytest.mark.parametrize(
    ("has_setup", "replicates", "expected"),
    [
        (True, False, ["up", "set up", "dump", "down"]),  # sonnets: its sources are read live
        (True, True, ["up", "set up", "seed", "no empty replica", "dump", "down"]),
        (False, True, ["up", "seed", "no empty replica", "dump", "down"]),
    ],
    ids=["setup-live", "setup-replicated", "no-setup"],
)
def test_a_demo_s_setup_runs_after_its_stores_come_up_and_before_its_seed(
    tmp_path, monkeypatch, has_setup, replicates, expected
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
    monkeypatch.setattr(
        builder, "_refuse_empty_replicas", lambda *_a: done.append("no empty replica")
    )
    monkeypatch.setattr(builder, "_replicates", lambda *_a: replicates)
    monkeypatch.setattr(builder.bundles, "pack", lambda _demo, _manifest: b"bundle")
    args = argparse.Namespace(
        name="sonnets", named_dir=named, out=tmp_path / "out", commit="a" * 40, timeout=60.0
    )
    assert builder.build(args) == 0
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


_REVIEWS = _REPO / "demo" / "named" / "reviews"


def test_document_search_and_graph_stores_are_dumped_by_their_role(tmp_path, monkeypatch):
    """REQ-2030: MongoDB as one archive, Elasticsearch as one snapshot copied out of its container,
    Neo4j stopped and dumped -- last, after every store that is read while running."""
    demo = tmp_path / "reviews"
    demo.mkdir()
    (demo / "docker-compose.yml").write_text("services: {}\n")
    stores = builder.Stores(demo)
    config = {
        "services": {
            "elasticsearch": {
                "image": "docker.elastic.co/elasticsearch/elasticsearch:8.13.0",
                "labels": {"com.provisa.demo.role": "search"},
                "environment": {"path.repo": "/usr/share/elasticsearch/snapshots"},
            },
            "mongodb": {
                "image": "mongo:7",
                "labels": {"com.provisa.demo.role": "document"},
                "environment": {
                    "MONGO_INITDB_ROOT_USERNAME": "root",
                    "MONGO_INITDB_ROOT_PASSWORD": "pw",
                },
            },
            "neo4j": {
                "image": "neo4j:5.19-community",
                "labels": {"com.provisa.demo.role": "graph"},
            },
            "seeder": {"image": "seed:1", "labels": {"com.provisa.demo.role": "seeder"}},
        }
    }
    ran: list[tuple] = []

    def _compose(*args, **kw):
        ran.append(args)
        if args[0] == "config":
            return type("Done", (), {"stdout": json.dumps(config)})()
        if args[0] == "port":
            return type("Done", (), {"stdout": "0.0.0.0:49200\n"})()
        if "mongodump" in args:
            kw["stdout"].write(b"archive bytes")
        return type("Done", (), {"stdout": ""})()

    asked: list[tuple] = []

    def _put(url, **kw):
        asked.append((url, kw.get("params"), kw.get("json")))
        body = {"snapshot": {"state": "SUCCESS"}} if url.endswith("/data") else {}
        return httpx.Response(200, json=body, request=httpx.Request("PUT", url))

    monkeypatch.setattr(stores, "_compose", _compose)
    monkeypatch.setattr(builder.httpx, "put", _put)

    assert stores.dump() == ["elasticsearch/data", "mongodb", "neo4j/neo4j"]
    assert (demo / "dump" / "mongodb.archive.gz").read_bytes() == b"archive bytes"
    assert asked == [
        (
            "http://127.0.0.1:49200/_snapshot/bundle",
            None,
            {"type": "fs", "settings": {"location": "/usr/share/elasticsearch/snapshots"}},
        ),
        (
            "http://127.0.0.1:49200/_snapshot/bundle/data",
            {"wait_for_completion": "true"},
            {"indices": "*,-.*", "include_global_state": False},
        ),
    ]
    commands = [a for a in ran if a[0] != "config"]
    assert commands == [
        ("port", "elasticsearch", "9200"),
        (
            "cp",
            "elasticsearch:/usr/share/elasticsearch/snapshots",
            str(demo / "dump" / "elasticsearch"),
        ),
        (
            "exec", "-T", "mongodb", "mongodump", "--quiet", "--archive", "--gzip",
            "--username", "root", "--password", "pw", "--authenticationDatabase", "admin",
        ),
        ("stop", "neo4j"),
        (
            "run", "--rm", "--no-deps", "-v", f"{demo / 'dump' / 'neo4j'}:/dumps",
            "--entrypoint", "neo4j-admin", "neo4j", "database", "dump", "neo4j",
            "--to-path=/dumps",
        ),
    ]  # fmt: skip


def test_the_reviews_run_time_compose_loads_what_its_build_saves():
    run = yaml.safe_load((_REVIEWS / "docker-compose.run.yml").read_text())["services"]
    built = yaml.safe_load((_REVIEWS / "docker-compose.yml").read_text())["services"]
    for name, role in (("mongodb", "document"), ("elasticsearch", "search"), ("neo4j", "graph")):
        assert run[name]["labels"]["com.provisa.demo.role"] == role
        assert built[name]["labels"]["com.provisa.demo.role"] == role
        assert built[name]["image"] == run[name]["image"]
        assert all(str(p).startswith("127.0.0.1:") for p in run[name]["ports"])
    assert "./dump/mongodb.archive.gz:/dump/mongodb.archive.gz:ro" in run["mongodb"]["volumes"]
    assert "./dump/elasticsearch:/snapshots:ro" in run["elasticsearch"]["volumes"]
    assert "./dump/neo4j:/dumps:ro" in run["neo4j"]["volumes"]
    # The build snapshots to the path its own store names; the run restores from /snapshots.
    assert built["elasticsearch"]["environment"]["path.repo"]
    assert run["elasticsearch"]["environment"]["path.repo"] == "/snapshots"
    assert run["neo4j"]["environment"]["NEO4J_dbms_databases_default__to__read__only"] == "true"
    # The reader config.yaml connects as is the one the run-time store makes.
    reader = (_REVIEWS / "db" / "mongo-reader.js").read_text()
    catalog = next(
        s for s in yaml.safe_load((_REVIEWS / "config.yaml").read_text())["sources"]
        if s["id"] == "catalog"
    )  # fmt: skip
    assert f'user: "{catalog["username"]}"' in reader and f'pwd: "{catalog["password"]}"' in reader


def test_the_build_hands_its_servers_the_variables_the_config_reads_and_no_other(
    tmp_path, monkeypatch
):
    """A govdata source is landed in the build with the account key its config reads; the
    servers the build starts get that variable from the build's environment, and nothing else of
    it."""
    (tmp_path / "config.yaml").write_text(
        "sources:\n- username: ${env:ASKAMERICA_API_KEY:-}\n  host: ${env:X_PG_HOST:-localhost}\n"
    )
    monkeypatch.setenv("ASKAMERICA_API_KEY", "key-1")
    monkeypatch.setenv("UNRELATED_SECRET", "not-handed-on")
    monkeypatch.delenv("X_PG_HOST", raising=False)
    assert builder._config_env(tmp_path) == {"ASKAMERICA_API_KEY": "key-1"}


def _seeded(tmp_path, rows: dict[str, int | None]):
    seeded = tmp_path / "insurance" / "seeded"
    seeded.mkdir(parents=True)
    (seeded / "replicas.json").write_text(
        json.dumps(
            {
                "replicas": [
                    {
                        "source_id": "govdata",
                        "schema_name": "disasters",
                        "table_name": name,
                        "completed_rows": count,
                    }
                    for name, count in rows.items()
                ]
            }
        )
    )
    return tmp_path / "insurance"


def test_a_replica_that_landed_no_rows_fails_the_build_by_name(tmp_path):
    """REQ-2037: a TTL -1 replica is landed once; an empty one would be served empty for good."""
    demo = _seeded(tmp_path, {"wildfire_risk_by_county": 3144, "storm": 0, "nri": None})
    with pytest.raises(SystemExit) as refused:
        builder._refuse_empty_replicas(demo)
    assert str(refused.value) == (
        "insurance: these replicas landed no rows: govdata.disasters.nri, govdata.disasters.storm"
    )


def test_replicas_that_all_landed_rows_pass(tmp_path):
    builder._refuse_empty_replicas(_seeded(tmp_path, {"nri": 3142, "wildfire": 3144}))


def test_the_bundle_job_carries_the_key_a_demo_lands_a_govdata_table_with():
    workflow = yaml.safe_load((_REPO / ".github" / "workflows" / "demo-bundles.yml").read_text())
    assert workflow["jobs"]["bundle"]["env"] == {
        "ASKAMERICA_API_KEY": "${{ secrets.ASKAMERICA_API_KEY }}"
    }
