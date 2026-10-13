# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-1911: a workload described in a contract, sized from a report into physical cores, workers
and in-flight requests per worker; any part the report has no model for refused by name; and the
sizing and tuning guide generated from the report."""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

BENCH = Path(__file__).resolve().parents[3] / "demo" / "named" / "perf" / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_model  # noqa: E402
import deployment_fixture as fx  # noqa: E402
import optimistic_load  # noqa: E402
import setup_contract as sc  # noqa: E402
import sizing as sz  # noqa: E402
import sizing_guide as guide  # noqa: E402

PERF_CONTRACT = BENCH / "setups" / "perf-stack.yaml"
ENV = {"PROVISA_HTTP_BASE_URL": "http://localhost:8001"}
TRANSPORTS = list(optimistic_load.TRANSPORTS)
DRAWS = 2_000
ZERO = {"fields": 1.0, "filters": 0.0, "rows": 1.0, "joins_same": 0.0, "joins_cross": 0.0}
WORKLOAD = {"rate_per_s": 1000, "transport_weights": {"graphql": 0.6, "pgwire": 0.4}}


def _raw(workload: dict[str, Any] | None = WORKLOAD) -> dict[str, Any]:
    raw = json.loads(json.dumps(yaml.safe_load(PERF_CONTRACT.read_text())))
    if workload is not None:
        raw["workload"] = workload
    return raw


def _setup(raw: dict[str, Any]) -> contract_model.Setup:
    return sc.setup_from_dict(raw, environ=ENV, known_transports=TRANSPORTS, deployment=fx.build())


def _cell(base: float, *, cache: dict | None = None, not_modelled: dict | None = None) -> dict:
    per_unit = {"fields": 0.01, "filters": 0.03, "rows": 0.001, "joins_same": 0.5}
    return {
        "provisa_cpu": {"base": base, "per_unit": per_unit, "r2": 0.99, "n": 9},
        "not_modelled": (
            {"joins_cross": "knob 'joins_cross' does not vary across the observations"}
            if not_modelled is None
            else not_modelled
        ),
        "baseline_knob_means": dict(ZERO),
        "replication": {"replication": "live", "ttl_seconds": 0, "route": "auto"},
        "cache": {"miss_ms": base, "opted_in_ms": 0.3, "opted_in_hit_ratio": 1.0, "hit_ms": 0.3}
        if cache is None
        else cache,
        "break_even": None,
        "mix_checks": [],
        "sizing": {"provisa_cpu_ms_per_request": base, "requests_per_s_per_core": 1000 / base},
    }


def _server(wpc: float, in_flight: int, factor: float) -> dict:
    return {
        "grid": [
            {
                "workers": 8,
                "request_threads": 1,
                "peak_req_per_s": 900.0,
                "p99_ms": 12.0,
                "concurrency": 64,
                "provisa_cpu_ms_per_request": 1.0,
            }
        ],
        "best_peak_req_per_s": 900.0,
        "workers": int(wpc * 8),
        "workers_per_physical_core": wpc,
        "in_flight_per_worker": in_flight,
        "peak_req_per_s": 900.0,
        "p99_ms": 12.0,
        "peak_req_per_s_per_physical_core": 112.5,
        "provisa_cpu_ms_per_request": 1.0,
        "capacity_factor": factor,
    }


def _report() -> dict[str, Any]:
    return {
        "label": "internal: not for publication",
        "hardware": {"physical_cores": 8, "shared_host": True},
        "tolerance": 0.05,
        "transports": {
            "graphql": {"bench-postgresql": _cell(2.0)},
            "pgwire": {"bench-postgresql": _cell(1.0)},
        },
        "server": {"graphql": _server(1.0, 1, 1.5), "pgwire": _server(2.0, 2, 1.6)},
        "skipped": [],
    }


# --- the contract's workload section ---------------------------------------------------------


def test_a_contract_describes_its_workload() -> None:
    setup = _setup(_raw())
    assert setup.workload == contract_model.Workload(1000, {"graphql": 0.6, "pgwire": 0.4})


def test_a_contract_without_a_workload_still_runs() -> None:
    assert _setup(_raw(None)).workload is None


@pytest.mark.parametrize(
    ("workload", "message"),
    [
        (
            {"rate_per_s": 0, "transport_weights": {"graphql": 1}},
            "workload.rate_per_s: must be > 0",
        ),
        (
            {"rate_per_s": 10, "transport_weights": {"graphql": 0.5}},
            "workload.transport_weights: weights sum to 0.5, must sum to 1",
        ),
        (
            {"rate_per_s": 10, "transport_weights": {"odbc": 1}},
            "workload.transport_weights: 'odbc' is not a transport of the contract",
        ),
        ({"rate_per_s": 10}, "workload"),
    ],
)
def test_an_invalid_workload_is_refused_naming_the_field(workload: dict, message: str) -> None:
    with pytest.raises(contract_model.SetupError, match=message):
        _setup(_raw(workload))


# --- sizing ------------------------------------------------------------------------------------


def test_the_workload_is_sized_into_physical_cores_workers_and_in_flight() -> None:
    sized = sz.size(_report(), _setup(_raw()), DRAWS)
    by = {t.transport: t for t in sized.transports}
    # every knob at zero and every request opted in: the same request each time, a hit after the
    # first
    hit = (DRAWS - 1) / DRAWS
    graphql_ms = hit * 0.3 + (1 - hit) * (2.0 + 0.01 * 1 + 0.001 * 1)
    pgwire_ms = hit * 0.3 + (1 - hit) * (1.0 + 0.01 * 1 + 0.001 * 1)
    assert by["graphql"].cpu_ms == pytest.approx(graphql_ms)
    assert by["pgwire"].cpu_ms == pytest.approx(pgwire_ms)
    assert by["graphql"].sources[0].hit_share == pytest.approx(hit)
    graphql_cores = 600 * graphql_ms / 1000 / 1.5
    pgwire_cores = 400 * pgwire_ms / 1000 / 1.6
    assert by["graphql"].physical_cores == pytest.approx(graphql_cores)
    assert sized.physical_cores == math.ceil(graphql_cores + pgwire_cores)
    # one worker count and one in-flight bound serve both: the larger of the two
    assert sized.workers == math.ceil(sized.physical_cores * 2.0)
    assert sized.in_flight_per_worker == 2


def test_uncached_requests_cost_the_model_at_the_workloads_knob_means() -> None:
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    raw["knobs"]["cache"] = {"probability": 0.0}
    raw["knobs"]["filters"] = {"probability": 1, "distribution": {"kind": "constant", "value": 2}}
    sized = sz.size(_report(), _setup(raw), DRAWS)
    (t,) = sized.transports
    (s,) = t.sources
    assert s.hit_share == 0 and s.hit_ms is None
    assert s.knob_means["filters"] == 2
    assert t.cpu_ms == pytest.approx(2.0 + 0.01 + 0.03 * 2 + 0.001)


def test_sizing_is_the_same_for_the_same_contract() -> None:
    assert sz.size(_report(), _setup(_raw()), DRAWS) == sz.size(_report(), _setup(_raw()), DRAWS)


def test_a_contract_with_no_workload_is_refused() -> None:
    with pytest.raises(sz.SizingRefused, match="workload: the contract describes no workload"):
        sz.size(_report(), _setup(_raw(None)), DRAWS)


def test_a_transport_without_a_worker_sweep_is_refused() -> None:
    report = _report()
    del report["server"]["pgwire"]
    with pytest.raises(sz.SizingRefused, match="pgwire: the run has no worker sweep"):
        sz.size(report, _setup(_raw()), DRAWS)


def test_a_source_without_a_cost_model_is_refused() -> None:
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    raw["knobs"]["source_weights"] = {
        "bench-postgresql": 0.5,
        "bench-clickhouse": 0.5,
        "bench-mongodb": 0.0,
        "bench-neo4j": 0.0,
    }
    with pytest.raises(
        sz.SizingRefused, match="graphql.bench-clickhouse: the run has no cost model"
    ):
        sz.size(_report(), _setup(raw), DRAWS)


def test_a_knob_the_run_could_not_cost_is_refused() -> None:
    report = _report()
    report["transports"]["graphql"]["bench-postgresql"] = _cell(
        2.0, not_modelled={"filters": "knob 'filters' does not vary across the observations"}
    )
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    raw["knobs"]["filters"] = {"probability": 1, "distribution": {"kind": "constant", "value": 1}}
    with pytest.raises(
        sz.SizingRefused,
        match="graphql.bench-postgresql: the workload sets filters but the run has no cost",
    ):
        sz.size(report, _setup(raw), DRAWS)


def test_a_route_hint_is_refused() -> None:
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    raw["transports"] = {"graphql": {}}  # a transport with a route hint
    raw["knobs"]["route"]["bench-postgresql"] = {"mode": "direct", "federated_probability": 0}
    with pytest.raises(sz.SizingRefused, match="route hints .* are not in the cost model"):
        sz.size(_report(), _setup(raw), DRAWS)


def test_a_replication_setting_other_than_the_measured_one_is_refused() -> None:
    report = _report()
    report["transports"]["graphql"]["bench-postgresql"]["replication"] = {
        "replication": "replica",
        "ttl_seconds": 300,
        "route": "auto",
    }
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    with pytest.raises(
        sz.SizingRefused,
        match="the workload reads it live .TTL 0 s.; the run measured it replica .TTL 300 s.",
    ):
        sz.size(report, _setup(raw), DRAWS)


def test_cache_hits_without_cache_figures_are_refused() -> None:
    report = _report()
    report["transports"]["graphql"]["bench-postgresql"]["cache"] = None
    raw = _raw({"rate_per_s": 100, "transport_weights": {"graphql": 1}})
    with pytest.raises(sz.SizingRefused, match="hit the response cache, and the run has no cache"):
        sz.size(report, _setup(raw), DRAWS)


# --- the guide ---------------------------------------------------------------------------------


def _with_break_even(report: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(report)
    out["transports"]["pgwire"]["bench-postgresql"]["break_even"] = {
        "live_ms": 2.0,
        "replica_ms": 0.5,
        "refresh_cpu_s": 3.0,
        "ttl_s": 60,
        "requests_per_s": 33.3333,
        "reason": None,
    }
    return out


def test_the_guide_gives_each_tuning_figure_with_its_report_statistic() -> None:
    text = guide.render(_with_break_even(_report()))
    assert text.startswith("# Provisa sizing and tuning guide\n")
    assert "8 physical cores" in text and "competed with it" in text
    # workers per physical core and in-flight per worker, by transport
    assert "| pgwire | 2.00 | 2 | 900 | 12.0 | 112 | 1.000 | 1.60 |" in text
    assert "`server.<transport>.workers_per_physical_core`" in text
    assert "`server.<transport>.in_flight_per_worker`" in text
    # the cache opt-in: miss, hit, saving
    assert "| graphql | bench-postgresql | 2.000 | 0.300 | 1.700 |" in text
    assert "`transports.<transport>.<source>.cache.hit_ms`" in text
    # live or replica, with the break-even and its TTL
    assert "| pgwire | bench-postgresql | 2.000 | 0.500 | 3.00 | 60 | 33.3 |" in text
    assert "`transports.<transport>.<source>.break_even.requests_per_s`" in text
    # a knob with no cost shows as such
    assert "| graphql | bench-postgresql | 2.000 | 0.0100 | 0.0300 | 0.0010 | 0.5000 | – |" in text


def test_the_guide_carries_no_internal_label() -> None:
    assert "internal" not in guide.render(_report()).lower()


def test_the_guide_sizes_a_workload() -> None:
    sized = sz.size(_report(), _setup(_raw()), DRAWS)
    text = guide.render(_report(), sized)
    assert "## Sizing this workload" in text
    assert (
        f"**{sized.physical_cores} physical cores, {sized.workers} worker processes, "
        f"{sized.in_flight_per_worker} in-flight requests per worker.**"
    ) in text
    assert "`server.<transport>.capacity_factor`" in text
