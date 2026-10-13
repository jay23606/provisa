# Copyright (c) 2026 Kenneth Stott
# Canary: 8c6bd429-9e01-4bcd-b8bd-2711f5bada79
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The report derived from a set of sweep runs (REQ-1911): per transport and source, a cost model
for Provisa's CPU per request and one for the source's (fitted over the uncached knob runs), the
cost of a response-cache hit and miss, the check of a mixed run against them, the break-even
between live and replica reads, and the per-core sizing inputs; per transport, the server's own
sizing from the worker sweep (worker processes per physical core, in-flight requests per worker,
and what a physical core delivers), with the hardware the sweep stated.

Reads what ``sweeps.py`` planned and ``run_benchmark.py --optimistic`` produced:

    <root>/manifest.json
    <root>/results/<run name>/optimistic/<transport>.json     (every step, server and source CPU)
    <root>/results/<run name>/optimistic/idle.json            (replica runs: the refresh cost)

    python bench_report.py --root results/sweeps --out results/sweeps/report.json [--tolerance 0.05]

The report is internal analysis: it is labelled so and is not for publication.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cost_model as cm

LABEL = "internal: not for publication"
_MODEL_RUNS = (
    "baseline",
    "fields",
    "filters",
    "rows",
    "joins_same_source",
    "joins_cross_source",
)
# a worker setting is enough when its peak is within this share of the best peak (--tolerance)
DEFAULT_TOLERANCE = 0.05


def _step(root: Path, run: Mapping[str, Any]) -> dict[str, Any]:
    """The run's lowest-concurrency step: the cost of a request, not of queueing."""
    path = root / "results" / run["name"] / "optimistic" / f"{run['transport']}.json"
    report = json.loads(path.read_text())
    if "error" in report:
        raise ValueError(f"{run['name']}: the transport reported {report['error']}")
    steps = [s for s in report["steps"] if "error" not in s]
    if not steps:
        raise ValueError(f"{run['name']}: no step completed")
    return min(steps, key=lambda s: s["concurrency"])


def _provisa_ms(run: Mapping[str, Any], step: Mapping[str, Any]) -> float:
    if "server_cpu_ms_per_request" not in step:
        raise ValueError(
            f"{run['name']}: no server_cpu_ms_per_request at concurrency {step['concurrency']} "
            "(was --server-pid given?)"
        )
    return step["server_cpu_ms_per_request"]


def _source_ms(run: Mapping[str, Any], step: Mapping[str, Any]) -> float | None:
    return (step.get("source_cpu_ms_per_request") or {}).get(run["source"])


def _replication(root: Path, run: Mapping[str, Any]) -> dict[str, Any]:
    """What the run measured its source under: the replication setting, its TTL and the route."""
    path = root / "results" / run["name"] / "optimistic" / f"{run['transport']}.json"
    return json.loads(path.read_text())["replication"][run["source"]]


def _model(
    observations: list[cm.Observation],
) -> tuple[dict[str, Any], dict[str, str], cm.CostModel]:
    """A model fitted over the knobs that vary: as a dict, the knobs that could not be costed
    with the reason, and the model itself."""
    varying = cm.varying_knobs(observations)
    not_modelled = {
        k: f"knob {k!r} does not vary across the observations" for k in cm.KNOBS if k not in varying
    }
    model = cm.fit(observations, varying)
    as_dict = {"base": model.base, "per_unit": model.marginal(), "r2": model.r2, "n": model.n}
    return as_dict, not_modelled, model


def _check(model: cm.CostModel, obs: cm.Observation) -> dict[str, float]:
    c = model.check(obs)
    return {
        "predicted_ms": c.predicted_ms,
        "measured_ms": c.measured_ms,
        "relative_error": c.relative_error,
    }


def _engine_ms(run: Mapping[str, Any], step: Mapping[str, Any], engine: str | None) -> float | None:
    """The engine container's CPU per request (the three-device benchmark's backends device
    reports it per step); None when the engine is not a container of its own."""
    if engine is None:
        return None
    cores = (step.get("backend_cpu_cores") or {}).get(engine)
    if cores is None:
        raise ValueError(
            f"{run['name']}: no CPU for the engine container {engine!r} at concurrency "
            f"{step['concurrency']} (was it a --backend-container?)"
        )
    attempts = step["requests"] + step["errors"]
    return cores * step["window_s"] / attempts * 1000


def _run_replication(root: Path, run: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    path = root / "results" / run["name"] / "optimistic" / f"{run['transport']}.json"
    return json.loads(path.read_text())["replication"]


def _between(
    root: Path, live: Mapping[str, Any], replica: Mapping[str, Any], engine: str | None
) -> dict[str, Any]:
    """The break-even between ``live`` and ``replica``, two runs that differ only in which
    sources are read from replicas. A request's cost is Provisa's CPU, the CPU of those sources
    and the engine's; the replica's standing cost is what the deployment burns idle, Provisa,
    those sources and the engine, over one TTL."""
    live_rep, replica_rep = _run_replication(root, live), _run_replication(root, replica)
    changed = sorted(
        s for s in replica_rep if replica_rep[s]["replication"] != live_rep[s]["replication"]
    )
    if not changed:
        raise ValueError(f"{live['name']} and {replica['name']} read every source the same way")

    def total_ms(run: Mapping[str, Any]) -> float:
        step = _step(root, run)
        by_source = step.get("source_cpu_ms_per_request") or {}
        missing = [s for s in changed if by_source.get(s) is None]
        if missing:
            raise ValueError(
                f"{run['name']}: no source CPU for {', '.join(missing)} "
                "(is the source container monitored?)"
            )
        engine_ms = _engine_ms(run, step, engine)
        return (
            _provisa_ms(run, step)
            + sum(by_source[s] for s in changed)
            + (engine_ms if engine_ms is not None else 0.0)
        )

    idle_path = root / "results" / replica["name"] / "optimistic" / "idle.json"
    if not idle_path.exists():
        raise ValueError(f"{replica['name']}: no idle.json (the refresh cost needs an idle window)")
    idle = json.loads(idle_path.read_text())
    if idle.get("source_cpu_error"):
        raise ValueError(
            f"{replica['name']}: the idle window's source CPU failed: {idle['source_cpu_error']}"
        )
    ttl = replica_rep[changed[0]]["ttl_seconds"]
    idle_cores = idle["server_cpu_cores"] + sum(idle["source_cpu_cores"][s] for s in changed)
    if engine is not None:
        idle_cores += idle["backend_cpu_cores"][engine]
    live_ms, replica_ms = total_ms(live), total_ms(replica)
    refresh = idle_cores * ttl
    be = cm.break_even(live_ms=live_ms, replica_ms=replica_ms, refresh_cpu_s=refresh, ttl_s=ttl)
    return {
        "sources": changed,
        "live_ms": live_ms,
        "replica_ms": replica_ms,
        "refresh_cpu_s": refresh,
        "ttl_s": ttl,
        "requests_per_s": be.requests_per_s,
        "reason": be.reason,
    }


def _break_even(
    root: Path, cell_runs: list[Mapping[str, Any]], engine: str | None
) -> dict[str, Any] | None:
    by_mode = {r["value"]: r for r in cell_runs if r["knob"] == "replication"}
    if not {"live", "replica"} <= set(by_mode):
        return None
    return _between(root, by_mode["live"], by_mode["replica"], engine)


def _join_break_even(
    root: Path, cell_runs: list[Mapping[str, Any]], engine: str | None
) -> dict[str, Any] | None:
    """Per cross-source join count, the break-even between reading both ends live and both from
    replicas (the join_replication runs)."""
    joins = [
        r for r in cell_runs if r["knob"] == "joins_cross_source" and r.get("join_replication")
    ]
    by = {(r["value"], r["join_replication"]): r for r in joins}
    values = sorted({v for v, k in by if (v, "both_live") in by and (v, "both_replica") in by})
    if not values:
        return None
    return {
        str(v): _between(root, by[(v, "both_live")], by[(v, "both_replica")], engine)
        for v in values
    }


def _cache(root: Path, cell_runs: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Provisa CPU of a response-cache miss (the uncached run) and of a hit, from the run with
    every request opted in: its measured cost less its misses at the miss cost, over its hits."""
    by_value = {r["value"]: r for r in cell_runs if r["knob"] == "cache"}
    if not {0.0, 1.0} <= set(by_value):
        return None
    miss_run, opted_run = by_value[0.0], by_value[1.0]
    miss_ms = _provisa_ms(miss_run, _step(root, miss_run))
    opted_step = _step(root, opted_run)
    hit_ratio = opted_step.get("hit_ratio")
    if not hit_ratio:
        raise ValueError(
            f"{opted_run['name']}: no cache hits measured (hit_ratio {hit_ratio!r}): "
            "the hit cost cannot be derived"
        )
    opted_ms = _provisa_ms(opted_run, opted_step)
    return {
        "miss_ms": miss_ms,
        "opted_in_ms": opted_ms,
        "opted_in_hit_ratio": hit_ratio,
        "hit_ms": (opted_ms - (1 - hit_ratio) * miss_ms) / hit_ratio,
    }


def _peak(root: Path, run: Mapping[str, Any]) -> dict[str, Any]:
    """The run's highest error-free throughput and its p99, and the CPU of a request at its
    lowest concurrency."""
    path = root / "results" / run["name"] / "optimistic" / f"{run['transport']}.json"
    report = json.loads(path.read_text())
    if "error" in report:
        raise ValueError(f"{run['name']}: the transport reported {report['error']}")
    clean = [s for s in report["steps"] if "error" not in s and s["errors"] == 0]
    if not clean:
        raise ValueError(f"{run['name']}: no step completed without errors")
    best = max(clean, key=lambda s: s["req_per_s"])
    return {
        **run["value"],
        "peak_req_per_s": best["req_per_s"],
        "p99_ms": best["p99_ms"],
        "concurrency": best["concurrency"],
        "provisa_cpu_ms_per_request": _provisa_ms(run, _step(root, run)),
    }


def _server(
    root: Path, runs: list[Mapping[str, Any]], physical_cores: int, tolerance: float
) -> dict[str, Any]:
    """One transport's worker sweep: every (workers, request threads) point, the fewest workers
    and then the fewest in-flight requests per worker whose peak is within ``tolerance`` of the
    best, and what a physical core delivers at that setting."""
    grid = [_peak(root, r) for r in runs]
    best = max(p["peak_req_per_s"] for p in grid)
    enough = (1 - tolerance) * best
    workers = min(p["workers"] for p in grid if p["peak_req_per_s"] >= enough)
    threads = min(
        p["request_threads"]
        for p in grid
        if p["workers"] == workers and p["peak_req_per_s"] >= enough
    )
    chosen = next(p for p in grid if (p["workers"], p["request_threads"]) == (workers, threads))
    per_core = chosen["peak_req_per_s"] / physical_cores
    return {
        "grid": sorted(grid, key=lambda p: (p["workers"], p["request_threads"])),
        "best_peak_req_per_s": best,
        "workers": workers,
        "workers_per_physical_core": workers / physical_cores,
        "in_flight_per_worker": threads,
        "peak_req_per_s": chosen["peak_req_per_s"],
        "p99_ms": chosen["p99_ms"],
        "peak_req_per_s_per_physical_core": per_core,
        "provisa_cpu_ms_per_request": chosen["provisa_cpu_ms_per_request"],
        # what a physical core delivers against the CPU one request costs on its own
        "capacity_factor": per_core * chosen["provisa_cpu_ms_per_request"] / 1000,
    }


def build_report(root: Path, tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text())
    runs = manifest["runs"]
    hardware = manifest["hardware"]
    # per engine, its own container when it is a server (the three-device benchmark)
    containers = manifest["engine_containers"]
    report: dict[str, Any] = {
        "label": LABEL,
        "hardware": hardware,
        "tolerance": tolerance,
        # per engine, side by side: its cost models, cache figures and break-evens
        "engines": {},
        "server": {},
        "skipped": [{"name": r["name"], "reason": r["skipped"]} for r in runs if r["skipped"]],
    }
    cells: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    worker_runs: dict[str, list[Mapping[str, Any]]] = {}
    for r in runs:
        if r["contract"] is None:
            continue
        if r["knob"] == "workers":
            worker_runs.setdefault(r["transport"], []).append(r)
        else:
            cells.setdefault((r["engine"], r["transport"], r["source"]), []).append(r)
    for transport, w_runs in worker_runs.items():
        report["server"][transport] = _server(root, w_runs, hardware["physical_cores"], tolerance)
    for (engine_name, transport, source), cell_runs in cells.items():
        engine = containers.get(engine_name)
        by_engine = report["engines"].setdefault(
            engine_name, {"engine_container": engine, "transports": {}}
        )
        model_runs = [r for r in cell_runs if r["knob"] in _MODEL_RUNS]
        steps = {r["name"]: _step(root, r) for r in cell_runs if r["knob"] in (*_MODEL_RUNS, "mix")}
        provisa_obs = [
            cm.Observation(steps[r["name"]]["knob_means"], _provisa_ms(r, steps[r["name"]]))
            for r in model_runs
        ]
        source_pairs = [(r, _source_ms(r, steps[r["name"]])) for r in model_runs]
        cell: dict[str, Any] = {}
        cell["provisa_cpu"], not_modelled, provisa_model = _model(provisa_obs)
        cell["not_modelled"] = not_modelled
        have = [(r, ms) for r, ms in source_pairs if ms is not None]
        source_model = None
        if have and len(have) != len(source_pairs):
            raise ValueError(
                f"{engine_name}.{transport}.{source}: source CPU is missing from some runs"
            )
        if have:
            source_obs = [cm.Observation(steps[r["name"]]["knob_means"], ms) for r, ms in have]
            cell["source_cpu"], _unused, source_model = _model(source_obs)
        else:
            cell["source_cpu"] = None  # no container monitored: source CPU was not measured
        # the engine's own CPU, when it runs in a container of its own: the cost of a request the
        # engine serves (a federated read, a cross-source join) shows here
        cell["engine_cpu"] = None
        if engine is not None:
            engine_obs = [
                cm.Observation(
                    steps[r["name"]]["knob_means"], _engine_ms(r, steps[r["name"]], engine)
                )
                for r in model_runs
            ]
            cell["engine_cpu"], _unused, _engine_model = _model(engine_obs)
        cell["mix_checks"] = []
        for r in (r for r in cell_runs if r["knob"] == "mix"):
            step = steps[r["name"]]
            means = step["knob_means"]
            check: dict[str, Any] = {
                "name": r["name"],
                "provisa_cpu": _check(provisa_model, cm.Observation(means, _provisa_ms(r, step))),
            }
            src_ms = _source_ms(r, step)
            check["source_cpu"] = (
                _check(source_model, cm.Observation(means, src_ms))
                if source_model is not None and src_ms is not None
                else None
            )
            cell["mix_checks"].append(check)
        baseline = next(r for r in cell_runs if r["knob"] == "baseline")
        base_ms = _provisa_ms(baseline, steps[baseline["name"]])
        cell["baseline_knob_means"] = steps[baseline["name"]]["knob_means"]
        cell["replication"] = _replication(root, baseline)
        cell["cache"] = _cache(root, cell_runs)
        cell["sizing"] = {
            "provisa_cpu_ms_per_request": base_ms,
            "requests_per_s_per_core": 1000 / base_ms,
        }
        cell["break_even"] = _break_even(root, cell_runs, engine)
        cell["join_break_even"] = _join_break_even(root, cell_runs, engine)
        by_engine["transports"].setdefault(transport, {})[source] = cell
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Report derived from knob sweep runs (internal)")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help="a worker setting is enough within this share of the best peak (0.05: 5%%)",
    )
    args = parser.parse_args()
    report = build_report(Path(args.root), args.tolerance)
    Path(args.out).write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
