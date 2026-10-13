# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-1911 knob join_replication: cross-source joins by how their two ends are read (both live,
both from replicas, one of each), drawn in the request mix, swept per class, costed per class, and
the break-even between both live and both from replicas."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

BENCH = Path(__file__).resolve().parents[3] / "demo" / "named" / "perf" / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_report as br  # noqa: E402
import contract_model  # noqa: E402
import deployment_fixture as fx  # noqa: E402
import optimistic_load as ol  # noqa: E402
import request_mix  # noqa: E402
import setup_contract as sc  # noqa: E402
import sweeps  # noqa: E402

PERF_CONTRACT = BENCH / "setups" / "perf-stack.yaml"
ENV = {"PROVISA_HTTP_BASE_URL": "http://localhost:8001"}
TRANSPORTS = list(ol.TRANSPORTS)
ZERO = {"probability": 0, "distribution": {"kind": "constant", "value": 0}}
ONE = {"probability": 1, "distribution": {"kind": "constant", "value": 1}}


def _raw() -> dict[str, Any]:
    raw = json.loads(json.dumps(yaml.safe_load(PERF_CONTRACT.read_text())))
    raw["transports"] = {"data_sql": {}}  # SQL joins either way round
    raw["knobs"]["joins_cross_source"] = ONE
    raw["knobs"]["source_weights"] = {
        "bench-postgresql": 0.5,
        "bench-clickhouse": 0.25,
        "bench-mongodb": 0.25,
        "bench-neo4j": 0.0,
    }
    return raw


def _read(raw: dict[str, Any], **settings: str) -> None:
    for source, setting in settings.items():
        raw["sources"][source]["replication"] = {
            "setting": setting,
            "ttl_seconds": 300 if setting == "replica" else 0,
        }


def _setup(raw: dict[str, Any]) -> contract_model.Setup:
    # a run sets the replication it declares (--apply-replication): not checked against the fixture
    return sc.setup_from_dict(
        raw,
        environ=ENV,
        known_transports=TRANSPORTS,
        deployment=fx.build(),
        verify_replication=False,
    )


def _specs(setup: contract_model.Setup, n: int = 400) -> list[request_mix.RequestSpec]:
    gen = request_mix.RequestGenerator(setup, "data_sql", "t", cacheable=True)
    return [gen.next() for _ in range(n)]


def _classes(specs: list[request_mix.RequestSpec]) -> Counter:
    return Counter(j.replication for s in specs for j in s.joins if j.kind == "cross")


# --- the contract --------------------------------------------------------------------------------


def test_the_knob_is_a_probability_and_a_weight_per_class() -> None:
    raw = _raw()
    raw["knobs"]["join_replication"] = {
        "probability": 0.5,
        "weights": {"both_live": 0.5, "mixed": 0.5},
    }
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    knob = _setup(raw).join_replication("data_sql")
    assert knob == contract_model.JoinReplication(0.5, {"both_live": 0.5, "mixed": 0.5})


@pytest.mark.parametrize(
    ("knob", "message"),
    [
        (
            {"probability": 1, "weights": {"half_live": 1}},
            "knobs.join_replication.weights: unknown class 'half_live'",
        ),
        (
            {"probability": 1, "weights": {"mixed": 0.4}},
            "knobs.join_replication.weights: weights sum to 0.4, must sum to 1",
        ),
        ({"probability": 1}, "knobs.join_replication"),
    ],
)
def test_an_invalid_knob_is_refused_naming_the_field(knob: dict, message: str) -> None:
    raw = _raw()
    raw["knobs"]["join_replication"] = knob
    with pytest.raises(contract_model.SetupError, match=message):
        _setup(raw)


def test_a_class_the_sources_settings_cannot_give_is_refused() -> None:
    # the perf stack reads Postgres live and the others from replicas: every join is mixed
    raw = _raw()
    raw["knobs"]["join_replication"] = {"probability": 1, "weights": {"both_live": 1}}
    with pytest.raises(
        contract_model.SetupError,
        match="knobs.join_replication.weights.both_live: on data_sql no table reaches 1 "
        "cross-source joins read both_live",
    ):
        _setup(raw)


def test_a_transport_overrides_the_knob() -> None:
    raw = _raw()
    raw["transports"]["data_sql"] = {
        "knobs": {"join_replication": {"probability": 1, "weights": {"mixed": 1}}}
    }
    assert _setup(raw).join_replication("data_sql").weights == {"mixed": 1}


# --- the request mix -----------------------------------------------------------------------------


def test_every_cross_source_join_carries_how_its_ends_are_read() -> None:
    raw = _raw()
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    classes = _classes(_specs(_setup(raw)))
    # Postgres-ClickHouse is read live at both ends; Postgres-MongoDB has one replica end
    assert set(classes) == {"both_live", "mixed"}


def test_the_knob_draws_joins_of_its_class() -> None:
    raw = _raw()
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    raw["knobs"]["join_replication"] = {"probability": 1, "weights": {"mixed": 1}}
    assert set(_classes(_specs(_setup(raw)))) == {"mixed"}


def test_the_knob_at_zero_leaves_every_other_draw_as_it_was() -> None:
    raw = _raw()
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    plain = _specs(_setup(raw))
    raw["knobs"]["join_replication"] = {"probability": 0, "weights": {"mixed": 1}}
    assert _specs(_setup(raw)) == plain


def test_the_mix_is_seeded() -> None:
    raw = _raw()
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    raw["knobs"]["join_replication"] = {
        "probability": 0.5,
        "weights": {"both_live": 0.5, "mixed": 0.5},
    }
    assert _specs(_setup(raw)) == _specs(_setup(raw))


def test_the_knob_means_count_cross_joins_per_class() -> None:
    raw = _raw()
    _read(raw, **{"bench-postgresql": "live", "bench-clickhouse": "live"})
    raw["knobs"]["join_replication"] = {"probability": 1, "weights": {"mixed": 1}}
    specs = _specs(_setup(raw), 50)
    means = ol.knob_means([(0.001, s, None, 1, 1) for s in specs])
    assert means is not None
    assert means["joins_cross_mixed"] == means["joins_cross"] == 1.0
    assert means["joins_cross_both_live"] == means["joins_cross_both_replica"] == 0.0


# --- the sweep ---------------------------------------------------------------------------------


def _plan(**kw: Any) -> dict[str, sweeps.SweepRun]:
    base = yaml.safe_load(PERF_CONTRACT.read_text())
    runs = sweeps.plan_sweeps(
        base,
        known_transports=TRANSPORTS,
        deployment=fx.build(),
        environ=ENV,
        transports=["data_sql"],
        sources=["bench-postgresql"],
        values={"joins_cross_source": [1]},
        cache=[],
        **kw,
    )
    return {r.name: r for r in runs}


def test_the_cross_join_values_run_once_per_class() -> None:
    runs = _plan(ttl_s=300)
    for klass in contract_model.JOIN_REPLICATION_CLASSES:
        run = runs[f"pg.data_sql.bench-postgresql.joins_cross_source.1.{klass}"]
        assert run.skipped is None, run.skipped
        assert run.join_replication == klass and run.apply_replication
        assert run.contract is not None
        assert run.contract["knobs"]["join_replication"] == {
            "probability": 1,
            "weights": {klass: 1.0},
        }
    both_replica = runs["pg.data_sql.bench-postgresql.joins_cross_source.1.both_replica"].contract
    assert both_replica is not None
    for s in ("bench-postgresql", "bench-clickhouse", "bench-mongodb"):
        assert both_replica["sources"][s]["replication"] == {
            "setting": "replica",
            "ttl_seconds": 300,
        }
    mixed = runs["pg.data_sql.bench-postgresql.joins_cross_source.1.mixed"].contract
    assert mixed is not None
    assert mixed["sources"]["bench-postgresql"]["replication"]["setting"] == "live"
    assert mixed["sources"]["bench-clickhouse"]["replication"]["setting"] == "replica"


def test_a_replica_class_without_a_ttl_is_skipped_with_the_reason() -> None:
    runs = _plan(ttl_s=0)
    assert runs["pg.data_sql.bench-postgresql.joins_cross_source.1.both_live"].skipped is None
    assert "need a replica TTL" in (
        runs["pg.data_sql.bench-postgresql.joins_cross_source.1.both_replica"].skipped or ""
    )


def test_a_run_that_sets_replication_applies_it() -> None:
    cmd = sweeps.run_command(
        "x.yaml",
        engine="pg",
        output_dir="out",
        python="python3",
        server_pid=None,
        apply_replication=True,
    )
    assert "--apply-replication" in cmd


# --- the report ----------------------------------------------------------------------------------

ENGINE = "perf-engine-postgresql-1"
OTHER = "bench-clickhouse"


def _run(
    root: Path,
    name: str,
    klass: str,
    *,
    provisa: float,
    sources: dict[str, float],
    engine_cores: float,
) -> dict[str, Any]:
    live = {"replication": "live", "ttl_seconds": 0, "route": "auto"}
    replica = {"replication": "replica", "ttl_seconds": 60, "route": "auto"}
    replication = {
        "bench-postgresql": replica if klass == "both_replica" else live,
        OTHER: live if klass == "both_live" else replica,
    }
    step = {
        "concurrency": 1,
        "window_s": 10.0,
        "requests": 1000,
        "errors": 0,
        "knob_means": {"fields": 1.0, "joins_cross_" + klass: 1.0},
        "server_cpu_ms_per_request": provisa,
        "source_cpu_ms_per_request": sources,
        "backend_cpu_cores": {ENGINE: engine_cores},
    }
    out = root / "results" / name / "optimistic"
    out.mkdir(parents=True)
    report = {"transport": "data_sql", "replication": replication, "steps": [step]}
    (out / "data_sql.json").write_text(json.dumps(report))
    return {
        "name": name,
        "transport": "data_sql",
        "source": "bench-postgresql",
        "knob": "joins_cross_source",
        "value": 1,
        "join_replication": klass,
    }


def test_the_join_break_even_counts_provisa_both_sources_and_the_engine(tmp_path: Path) -> None:
    # engine 0.1 cores over 10 s and 1000 requests: 1 ms per request
    live = _run(
        tmp_path,
        "live",
        "both_live",
        provisa=1.0,
        sources={"bench-postgresql": 1.0, OTHER: 2.0},
        engine_cores=0.1,
    )
    rep = _run(
        tmp_path,
        "replica",
        "both_replica",
        provisa=1.0,
        sources={"bench-postgresql": 0.2, OTHER: 0.3},
        engine_cores=0.05,
    )
    (tmp_path / "results" / "replica" / "optimistic" / "idle.json").write_text(
        json.dumps(
            {
                "window_s": 120.0,
                "server_cpu_cores": 0.01,
                "source_cpu_cores": {"bench-postgresql": 0.02, OTHER: 0.03},
                "backend_cpu_cores": {ENGINE: 0.04},
                "source_cpu_error": None,
            }
        )
    )
    be = br._join_break_even(tmp_path, [live, rep], ENGINE)
    assert be is not None
    one = be["1"]
    assert one["sources"] == sorted(["bench-postgresql", OTHER])
    assert one["live_ms"] == pytest.approx(1.0 + 3.0 + 1.0)
    assert one["replica_ms"] == pytest.approx(1.0 + 0.5 + 0.5)
    assert one["refresh_cpu_s"] == pytest.approx((0.01 + 0.05 + 0.04) * 60)
    assert one["requests_per_s"] == pytest.approx(0.1 * 1000 / 3.0)


def test_the_engines_cpu_needs_its_container_in_every_step(tmp_path: Path) -> None:
    run = _run(
        tmp_path, "r", "both_live", provisa=1.0, sources={"bench-postgresql": 1.0}, engine_cores=0
    )
    step = json.loads((tmp_path / "results" / "r" / "optimistic" / "data_sql.json").read_text())[
        "steps"
    ][0]
    assert br._engine_ms(run, step, ENGINE) == 0.0
    assert br._engine_ms(run, step, None) is None
    del step["backend_cpu_cores"]
    with pytest.raises(ValueError, match="no CPU for the engine container"):
        br._engine_ms(run, step, ENGINE)
