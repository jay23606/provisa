# Copyright (c) 2026 Kenneth Stott
# Canary: 1352605b-3423-46bc-8638-e8c7c1b5b2ea
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-1911: each knob swept alone, per transport and per source — the contracts that make the
runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

BENCH = Path(__file__).resolve().parents[3] / "demo" / "named" / "perf" / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_model  # noqa: E402
import deployment_fixture as fx  # noqa: E402
import optimistic_load as ol  # noqa: E402
import setup_contract as sc  # noqa: E402
import sweeps  # noqa: E402

PERF_CONTRACT = BENCH / "setups" / "perf-stack.yaml"
ENV = {"PROVISA_HTTP_BASE_URL": "http://localhost:8001"}
TRANSPORTS = list(ol.TRANSPORTS)


def _base() -> dict:
    return yaml.safe_load(PERF_CONTRACT.read_text())


_NO_REST = fx.build(drop={"order_events": {"rest"}})


def _plan(**kw) -> list[sweeps.SweepRun]:
    kw.setdefault("deployment", fx.build())
    return sweeps.plan_sweeps(_base(), known_transports=TRANSPORTS, environ=ENV, **kw)


def _by_name(runs: list[sweeps.SweepRun]) -> dict[str, sweeps.SweepRun]:
    return {r.name: r for r in runs}


def _load(run: sweeps.SweepRun, tmp_path: Path) -> contract_model.Setup:
    assert run.contract is not None
    path = tmp_path / f"{run.name}.yaml"
    path.write_text(yaml.safe_dump(run.contract, sort_keys=False))
    return sc.load_setup(path, environ=ENV, known_transports=TRANSPORTS, deployment=fx.build())


def test_one_knob_at_a_time_per_transport_and_source(tmp_path: Path) -> None:
    runs = _by_name(
        _plan(
            transports=["pgwire"],
            sources=["bench-postgresql"],
            values={"fields": [1, 3], "rows": [10]},
            cache=[],
        )
    )
    assert set(runs) == {
        "pg.pgwire.bench-postgresql.baseline",
        "pg.pgwire.bench-postgresql.fields.1",
        "pg.pgwire.bench-postgresql.fields.3",
        "pg.pgwire.bench-postgresql.rows.10",
    }
    base = _load(runs["pg.pgwire.bench-postgresql.baseline"], tmp_path)
    fields3 = _load(runs["pg.pgwire.bench-postgresql.fields.3"], tmp_path)
    assert list(base.transports) == ["pgwire"]
    assert base.knobs.source_weights == {
        "bench-postgresql": 1.0,
        "bench-clickhouse": 0.0,
        "bench-mongodb": 0.0,
        "bench-neo4j": 0.0,
    }
    for name, knob in base.knobs.distributions.items():
        assert knob.probability == 0, name
    f = fields3.knobs.distributions["fields"]
    assert (f.probability, f.distribution.kind, f.distribution.params["value"]) == (
        1,
        "constant",
        3,
    )
    # everything else is the baseline's
    others = {n: k for n, k in fields3.knobs.distributions.items() if n != "fields"}
    assert all(k.probability == 0 for k in others.values())


def test_a_variant_that_the_contract_cannot_serve_is_skipped_with_the_reason() -> None:
    runs = _by_name(
        _plan(
            transports=["rest"],
            sources=["bench-clickhouse"],
            values={"fields": [1]},
            deployment=_NO_REST,
        )
    )
    run = runs["pg.rest.bench-clickhouse.baseline"]
    assert run.contract is None
    assert "is not exposed in rest by the deployment" in run.skipped


def test_joins_the_transport_cannot_express_are_skipped() -> None:
    runs = _by_name(
        _plan(transports=["grpc"], sources=["bench-postgresql"], values={"joins_same_source": [1]})
    )
    assert runs["pg.grpc.bench-postgresql.baseline"].contract is not None
    assert (
        "joins cannot be expressed on grpc"
        in runs["pg.grpc.bench-postgresql.joins_same_source.1"].skipped
    )


def test_more_fields_than_the_table_has_is_skipped() -> None:
    runs = _by_name(
        _plan(transports=["data_sql"], sources=["bench-mongodb"], values={"fields": [2, 9]})
    )
    assert runs["pg.data_sql.bench-mongodb.fields.2"].contract is not None
    assert "draws up to 9 fields" in runs["pg.data_sql.bench-mongodb.fields.9"].skipped


def test_cache_sweep() -> None:
    runs = _by_name(
        _plan(transports=["graphql"], sources=["bench-postgresql"], values={}, cache=[0.0, 0.5])
    )
    assert runs["pg.graphql.bench-postgresql.cache.0.0"].contract["knobs"]["cache"] == {
        "probability": 0.0
    }
    assert runs["pg.graphql.bench-postgresql.cache.0.5"].contract["knobs"]["cache"] == {
        "probability": 0.5
    }
    # knob runs are uncached, so a knob's cost is never mixed with the cache's
    assert runs["pg.graphql.bench-postgresql.baseline"].contract["knobs"]["cache"] == {
        "probability": 0.0
    }


def test_replication_sweep_sets_the_setting_and_its_ttl(tmp_path: Path) -> None:
    runs = _by_name(
        _plan(
            transports=["data_sql"],
            sources=["bench-postgresql"],
            values={},
            replication=["live", "replica"],
            ttl_s=300,
        )
    )
    live = runs["pg.data_sql.bench-postgresql.replication.live"].contract
    replica = runs["pg.data_sql.bench-postgresql.replication.replica"].contract
    assert live["sources"]["bench-postgresql"]["replication"] == {
        "setting": "live",
        "ttl_seconds": 0,
    }
    assert replica["sources"]["bench-postgresql"]["replication"] == {
        "setting": "replica",
        "ttl_seconds": 300,
    }
    # the deployment need not already have it: a replication run applies the setting itself
    assert runs["pg.data_sql.bench-postgresql.replication.replica"].skipped is None


def test_a_replica_without_a_ttl_is_skipped() -> None:
    runs = _by_name(
        _plan(
            transports=["data_sql"],
            sources=["bench-clickhouse"],
            values={},
            replication=["replica"],
            ttl_s=0,
        )
    )
    assert (
        "a replica needs its refresh TTL"
        in runs["pg.data_sql.bench-clickhouse.replication.replica"].skipped
    )


def test_the_default_plan_covers_every_transport_and_source() -> None:
    runs = _plan()
    names = {r.name for r in runs}
    for t in TRANSPORTS:
        for s in ("bench-postgresql", "bench-clickhouse", "bench-mongodb", "bench-neo4j"):
            assert f"pg.{t}.{s}.baseline" in names
    # every run is either a loadable contract or says why not
    assert all((r.contract is None) != (r.skipped is None) for r in runs)
    assert any(r.contract is not None for r in runs)


def test_write_plan_writes_contracts_and_a_manifest(tmp_path: Path) -> None:
    runs = _plan(
        transports=["pgwire", "rest"],
        sources=["bench-postgresql", "bench-clickhouse"],
        values={"rows": [10]},
        deployment=_NO_REST,
    )
    sweeps.write_plan(runs, tmp_path, hardware=sweeps.Hardware(8, True))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    by = {m["name"]: m for m in manifest["runs"]}
    assert (
        by["pg.pgwire.bench-postgresql.rows.10"]["contract"]
        == "pg.pgwire.bench-postgresql.rows.10.yaml"
    )
    assert (tmp_path / "pg.pgwire.bench-postgresql.rows.10.yaml").exists()
    assert by["pg.rest.bench-clickhouse.baseline"]["contract"] is None
    assert (
        "is not exposed in rest by the deployment"
        in by["pg.rest.bench-clickhouse.baseline"]["skipped"]
    )
    assert by["pg.pgwire.bench-postgresql.rows.10"] == {
        "name": "pg.pgwire.bench-postgresql.rows.10",
        "transport": "pgwire",
        "source": "bench-postgresql",
        "knob": "rows",
        "value": 10,
        "contract": "pg.pgwire.bench-postgresql.rows.10.yaml",
        "skipped": None,
        "server_env": {"PROVISA_ENGINE": "pg"},
        "join_replication": None,
        "apply_replication": False,
        "engine": "pg",
    }
    assert manifest["label"] == "internal: not for publication"
    assert manifest["hardware"] == {"physical_cores": 8, "shared_host": True}


def test_the_run_command_for_a_contract() -> None:
    cmd = sweeps.run_command(
        "x.yaml", engine="pg", output_dir="results/sweeps/x", python="python3", server_pid=123
    )
    assert cmd == [
        "python3",
        "run_benchmark.py",
        "--engine",
        "pg",
        "--optimistic",
        "--setup",
        "x.yaml",
        "--server-pid",
        "123",
        "--output-dir",
        "results/sweeps/x",
    ]


def test_the_worker_sweep_plans_each_pair_of_workers_and_in_flight_per_transport(
    tmp_path: Path,
) -> None:
    runs = _by_name(
        sweeps.plan_worker_sweep(
            _base(),
            known_transports=TRANSPORTS,
            deployment=fx.build(),
            environ=ENV,
            transports=["graphql", "pgwire"],
            workers=[8, 16],
            request_threads=[1, 4],
        )
    )
    assert set(runs) == {
        f"{t}.workers.{w}.threads.{r}"
        for t in ("graphql", "pgwire")
        for w in (8, 16)
        for r in (1, 4)
    }
    run = runs["pgwire.workers.16.threads.4"]
    assert run.knob == "workers" and run.value == {"workers": 16, "request_threads": 4}
    assert run.server_env == {
        "PROVISA_WORKERS": "16",
        "PROVISA_REQUEST_THREADS": "4",
        "PROVISA_ENGINE": "pg",
    }
    # the base contract as it stands, one transport: the optimistic request
    setup = _load(run, tmp_path)
    assert list(setup.transports) == ["pgwire"]
    assert setup.knobs.cache_probability == 1.0
    assert all(k.probability == 0 for k in setup.knobs.distributions.values())


def test_a_worker_sweep_transport_the_deployment_cannot_serve_is_skipped() -> None:
    base = _base()
    base["knobs"]["source_weights"] = {
        "bench-postgresql": 0.0,
        "bench-clickhouse": 1.0,
        "bench-mongodb": 0.0,
        "bench-neo4j": 0.0,
    }
    runs = sweeps.plan_worker_sweep(
        base,
        known_transports=TRANSPORTS,
        deployment=_NO_REST,
        environ=ENV,
        transports=["rest"],
        workers=[8],
        request_threads=[1],
    )
    (run,) = runs
    assert run.contract is None
    assert "is not exposed in rest by the deployment" in run.skipped


def test_the_manifest_carries_a_worker_runs_server_environment(tmp_path: Path) -> None:
    runs = sweeps.plan_worker_sweep(
        _base(),
        known_transports=TRANSPORTS,
        deployment=fx.build(),
        environ=ENV,
        transports=["graphql"],
        workers=[4],
        request_threads=[2],
    )
    sweeps.write_plan(runs, tmp_path, hardware=sweeps.Hardware(16, False))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (entry,) = manifest["runs"]
    assert entry["server_env"] == {
        "PROVISA_WORKERS": "4",
        "PROVISA_REQUEST_THREADS": "2",
        "PROVISA_ENGINE": "pg",
    }
    assert manifest["hardware"] == {"physical_cores": 16, "shared_host": False}


def test_the_knob_sweep_runs_once_per_engine_kept_apart() -> None:
    runs = _by_name(
        _plan(
            transports=["pgwire"],
            sources=["bench-postgresql"],
            values={"rows": [10]},
            cache=[],
            engines=["pg", "duckdb", "trino"],
        )
    )
    assert set(runs) == {
        f"{e}.pgwire.bench-postgresql.{k}"
        for e in ("pg", "duckdb", "trino")
        for k in ("baseline", "rows.10")
    }
    run = runs["duckdb.pgwire.bench-postgresql.rows.10"]
    assert run.engine == "duckdb"
    assert run.server_env == {"PROVISA_ENGINE": "duckdb"}


def test_an_unknown_engine_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown engine 'spark'"):
        _plan(transports=["pgwire"], sources=["bench-postgresql"], engines=["spark"])


def test_the_manifest_names_each_engines_container(tmp_path: Path) -> None:
    runs = _plan(transports=["pgwire"], sources=["bench-postgresql"], values={}, cache=[])
    sweeps.write_plan(
        runs,
        tmp_path,
        hardware=sweeps.Hardware(16, False),
        engine_containers={"pg": "perf-engine-postgresql-1"},
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["engine_containers"] == {"pg": "perf-engine-postgresql-1"}
