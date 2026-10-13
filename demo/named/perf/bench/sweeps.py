# Copyright (c) 2026 Kenneth Stott
# Canary: 966443cc-224a-4735-9264-309ab8f96917
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""Knob sweeps (REQ-1911): each knob alone, per transport and per source, as setup contracts.

A sweep run is the base contract with every knob at zero, one transport, all weight on one source
and one knob set. Knob runs are uncached (cache probability 0), so a knob's cost is never mixed
with the cache's; the cache runs (``cache``) are the hit and miss figures, kept apart. ``plan_sweeps``
builds every run and validates it with the contract loader; a run the contract cannot serve (a
transport that cannot spell the source's tables, joins on gRPC, more fields than the table has) is
listed with the reason, never dropped.

``plan_worker_sweep`` plans the server's own sizing: the base contract per transport, run against a
server started with each pair of worker processes (``PROVISA_WORKERS``) and in-flight requests per
worker (``concurrency.request_threads``, ``PROVISA_REQUEST_THREADS``). Such a run carries the
environment its server is started with (``server_env``); ``orchestrate.sh`` passes the caller's
environment to the server.

``write_plan`` writes the contracts and a manifest with the server's hardware as stated (physical
cores, and whether the sources and the load generator shared its host); ``run_command`` is the
command that runs one.

    python sweeps.py plan --setup setups/perf-stack.yaml --out results/sweeps \
        --physical-cores 8 --shared-host yes --workers 4,8,16 --request-threads 1,2,4
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import contract_model
import lookup
import setup_contract as sc
import yaml

LABEL = "internal: not for publication"
DEFAULT_VALUES: dict[str, list[int]] = {
    "fields": [1, 2, 4],
    "filters": [1, 2],
    "rows": [1, 10, 100, 1000],
    "joins_same_source": [1],
    "joins_cross_source": [1, 2],
}
DEFAULT_CACHE = [0.0, 1.0]
DEFAULT_JOIN_REPLICATION = contract_model.JOIN_REPLICATION_CLASSES
ENGINES = ("pg", "duckdb", "trino")
DEFAULT_ENGINES = ("pg",)
ENGINE_ENV = "PROVISA_ENGINE"
# the server settings a worker sweep run is started with
WORKERS_ENV = "PROVISA_WORKERS"
REQUEST_THREADS_ENV = "PROVISA_REQUEST_THREADS"
_ZERO_KNOB = {"probability": 0, "distribution": {"kind": "constant", "value": 0}}


@dataclass(frozen=True)
class SweepRun:
    name: str
    transport: str
    source: str
    knob: str  # baseline | a distribution knob | cache | replication | workers
    value: Any
    contract: dict[str, Any] | None  # the loadable contract, or None
    skipped: str | None  # why there is no contract
    # the environment the server under test is started with (worker sweep runs); None: any
    server_env: dict[str, str] | None = None
    # a cross-source join run: how its joins' two ends are read (JOIN_REPLICATION_CLASSES)
    join_replication: str | None = None
    # the run sets replication itself (run_benchmark --apply-replication)
    apply_replication: bool = False
    # the federation engine the server under test is started with (PROVISA_ENGINE)
    engine: str = "pg"


def _constant(n: int) -> dict[str, Any]:
    return {"probability": 1, "distribution": {"kind": "constant", "value": n}}


def _baseline(
    raw: dict[str, Any], transport: str, source: str, spread: Sequence[str]
) -> dict[str, Any]:
    """The base contract with every knob at zero and uncached, one transport, weight on
    ``source`` (and on ``spread``, equally, when a knob needs other sources to reach)."""
    out = copy.deepcopy(raw)
    k = out["knobs"]
    for name in contract_model.DISTRIBUTION_KNOBS:
        k[name] = copy.deepcopy(_ZERO_KNOB)
    k["cache"] = {"probability": 0.0}
    sources = list(out["sources"])
    on = {source, *spread}
    k["source_weights"] = {s: (1.0 / len(on) if s in on else 0.0) for s in sources}
    for s in sources:
        k["route"][s] = {"mode": "auto", "federated_probability": 0}
    out["transports"] = {transport: {}}
    return out


def _read_as(
    contract: dict[str, Any], source: str, spread: Sequence[str], klass: str, ttl_s: int
) -> str | None:
    """Set the replication of the request's source and the sources its cross-source joins reach
    so the joins are read as ``klass``: both ends live, both from replicas, or the request's own
    source live and the others from replicas. The reason it cannot be, or None."""
    if klass != "both_live" and ttl_s <= 0:
        return f"cross-source joins read {klass} need a replica TTL (--ttl)"
    live = {"setting": "live", "ttl_seconds": 0}
    replica = {"setting": "replica", "ttl_seconds": ttl_s}
    for s in {source, *spread}:
        if klass == "both_live" or (klass == "mixed" and s == source):
            contract["sources"][s]["replication"] = dict(live)
        else:
            contract["sources"][s]["replication"] = dict(replica)
    # every cross-source join a request draws is of this class
    contract["knobs"]["join_replication"] = {"probability": 1, "weights": {klass: 1.0}}
    return None


def _cross_sources(raw: Mapping[str, Any]) -> list[str]:
    ends: list[str] = []
    for j in raw.get("cross_source_joins", []):
        for side in ("left", "right"):
            s = j[side].partition(":")[0]
            if s not in ends:
                ends.append(s)
    return ends


def _validate(
    contract: dict[str, Any],
    known_transports: Sequence[str],
    environ: Mapping[str, str],
    deployment: Any,
) -> str | None:
    try:
        # a replication sweep is run with --apply-replication, so the deployment need not have it
        sc.setup_from_dict(
            contract,
            environ=environ,
            known_transports=known_transports,
            deployment=deployment,
            verify_replication=False,
        )
    except contract_model.SetupError as exc:
        return str(exc)
    return None


def plan_sweeps(
    base: Mapping[str, Any],
    *,
    known_transports: Sequence[str],
    deployment: Any,
    environ: Mapping[str, str] | None = None,
    transports: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    values: Mapping[str, Sequence[int]] | None = None,
    cache: Sequence[float] | None = None,
    replication: Sequence[str] = (),
    ttl_s: int = 0,
    join_replication: Sequence[str] = DEFAULT_JOIN_REPLICATION,
    engines: Sequence[str] = DEFAULT_ENGINES,
) -> list[SweepRun]:
    """``join_replication``: the cross-source join values are run once per class, each with the
    sources set so every join is read that way. ``engines``: the whole knob sweep runs once per
    engine, against a server started with it (``server_env``), each engine's runs named and
    reported apart."""
    unknown = [e for e in engines if e not in ENGINES]
    if unknown:
        raise ValueError(f"unknown engine {unknown[0]!r} (known: {', '.join(ENGINES)})")
    env = os.environ if environ is None else environ
    wanted_values = DEFAULT_VALUES if values is None else values
    wanted_cache = DEFAULT_CACHE if cache is None else cache
    runs: list[SweepRun] = []
    for transport in transports or list(base["transports"]):
        for source in sources or list(base["sources"]):
            # (knob, value, contract, join class, why it cannot run)
            variants: list[tuple[str, Any, dict[str, Any], str | None, str | None]] = []
            plain = _baseline(dict(base), transport, source, [])
            variants.append(("baseline", None, plain, None, None))
            for knob, vals in wanted_values.items():
                if knob == "joins_cross_source":
                    spread = _cross_sources(base)
                    for v in vals:
                        for klass in join_replication:
                            c = _baseline(dict(base), transport, source, spread)
                            c["knobs"][knob] = _constant(v)
                            why = _read_as(c, source, spread, klass, ttl_s)
                            variants.append((knob, v, c, klass, why))
                    continue
                for v in vals:
                    c = _baseline(dict(base), transport, source, [])
                    c["knobs"][knob] = _constant(v)
                    variants.append((knob, v, c, None, None))
            for p in wanted_cache:
                c = _baseline(dict(base), transport, source, [])
                c["knobs"]["cache"] = {"probability": p}
                variants.append(("cache", p, c, None, None))
            for setting in replication:
                c = _baseline(dict(base), transport, source, [])
                c["sources"][source]["replication"] = {
                    "setting": setting,
                    "ttl_seconds": ttl_s if setting == "replica" else 0,
                }
                variants.append(("replication", setting, c, None, None))
            for knob, value, contract, klass, why in variants:
                name = (
                    f"{transport}.{source}.{knob}"
                    + ("" if value is None else f".{value}")
                    + ("" if klass is None else f".{klass}")
                )
                reason = why or _validate(contract, known_transports, env, deployment)
                for engine in engines:
                    runs.append(
                        SweepRun(
                            f"{engine}.{name}",
                            transport,
                            source,
                            knob,
                            value,
                            None if reason else contract,
                            reason,
                            server_env={ENGINE_ENV: engine},
                            join_replication=klass,
                            apply_replication=knob == "replication" or klass is not None,
                            engine=engine,
                        )
                    )
    return runs


def plan_worker_sweep(
    base: Mapping[str, Any],
    *,
    known_transports: Sequence[str],
    deployment: Any,
    workers: Sequence[int],
    request_threads: Sequence[int],
    environ: Mapping[str, str] | None = None,
    transports: Sequence[str] | None = None,
    engine: str = DEFAULT_ENGINES[0],
) -> list[SweepRun]:
    """Per transport, the base contract as it stands (the optimistic request when its knobs are
    at zero) against a server started with each (workers, request threads) pair. The optimistic
    request reaches no engine, so the server's sizing is swept under one, ``engine``."""
    env = os.environ if environ is None else environ
    runs: list[SweepRun] = []
    for transport in transports or list(base["transports"]):
        contract = copy.deepcopy(dict(base))
        contract["transports"] = {transport: base["transports"][transport]}
        contract.pop("workload", None)
        reason = _validate(contract, known_transports, env, deployment)
        for w in workers:
            for r in request_threads:
                runs.append(
                    SweepRun(
                        f"{transport}.workers.{w}.threads.{r}",
                        transport,
                        "",
                        "workers",
                        {"workers": w, "request_threads": r},
                        None if reason else contract,
                        reason,
                        {WORKERS_ENV: str(w), REQUEST_THREADS_ENV: str(r), ENGINE_ENV: engine},
                        engine=engine,
                    )
                )
    return runs


@dataclass(frozen=True)
class Hardware:
    """The server's hardware as stated by whoever runs the sweep, never guessed."""

    physical_cores: int
    shared_host: bool  # the sources and the load generator ran on the server's host


def write_plan(
    runs: Sequence[SweepRun],
    out_dir: Path,
    *,
    hardware: Hardware,
    engine_containers: Mapping[str, str] | None = None,
) -> None:
    """``engine_containers``: per engine, its own container on the backends device (the
    three-device benchmark's pg or Trino), whose CPU the report costs beside Provisa's and the
    sources'; an engine left out runs inside Provisa (DuckDB) or is not measured apart."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for r in runs:
        file = None
        if r.contract is not None:
            file = f"{r.name}.yaml"
            (out_dir / file).write_text(yaml.safe_dump(r.contract, sort_keys=False))
        manifest.append(
            {
                "name": r.name,
                "transport": r.transport,
                "source": r.source,
                "knob": r.knob,
                "value": r.value,
                "contract": file,
                "skipped": r.skipped,
                "server_env": r.server_env,
                "join_replication": r.join_replication,
                "apply_replication": r.apply_replication,
                "engine": r.engine,
            }
        )
    body = {
        "label": LABEL,
        "hardware": {
            "physical_cores": hardware.physical_cores,
            "shared_host": hardware.shared_host,
        },
        "engine_containers": dict(engine_containers or {}),
        "runs": manifest,
    }
    (out_dir / "manifest.json").write_text(json.dumps(body, indent=2))


def run_command(
    contract: str,
    *,
    engine: str,
    output_dir: str,
    python: str,
    server_pid: int | None,
    apply_replication: bool = False,
) -> list[str]:
    """The command that runs one sweep contract (from the bench directory), against a server
    started with the run's ``server_env`` when it has one. A run that sets replication itself
    (the manifest's ``apply_replication``) sets it through the admin API and restores it."""
    cmd = [python, "run_benchmark.py", "--engine", engine, "--optimistic", "--setup", contract]
    if server_pid is not None:
        cmd += ["--server-pid", str(server_pid)]
    if apply_replication:
        cmd.append("--apply-replication")
    return cmd + ["--output-dir", output_dir]


def main() -> int:
    import optimistic_load

    parser = argparse.ArgumentParser(description="Plan knob sweeps as setup contracts")
    parser.add_argument("command", choices=["plan"])
    parser.add_argument("--setup", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--resolved-names",
        required=True,
        help="resolved-names.json a run wrote: what the deployment calls the contract's tables",
    )
    parser.add_argument("--replication", default="", help="live,replica: sweep the setting")
    parser.add_argument("--ttl", type=int, default=0)
    parser.add_argument(
        "--physical-cores",
        type=int,
        required=True,
        help="the server's physical cores (lscpu: cores per socket x sockets), not its threads",
    )
    parser.add_argument(
        "--shared-host",
        choices=["yes", "no"],
        required=True,
        help="whether the sources and the load generator run on the server's host",
    )
    parser.add_argument(
        "--engines",
        default=",".join(DEFAULT_ENGINES),
        help="pg,duckdb,trino: the knob sweep runs once per engine, the server restarted with "
        "each (default: pg)",
    )
    parser.add_argument(
        "--engine-container",
        action="append",
        default=[],
        help="ENGINE=CONTAINER: the engine's own container (pg=perf-engine-postgresql-1), whose "
        "CPU each run reports as a --backend-container; repeatable. Leave out an engine that runs "
        "inside Provisa (duckdb)",
    )
    parser.add_argument("--workers", default="", help="4,8,16: worker processes to sweep")
    parser.add_argument(
        "--request-threads", default="", help="1,2,4: in-flight requests per worker to sweep"
    )
    args = parser.parse_args()
    engines = [e for e in args.engines.split(",") if e]
    containers = dict(c.split("=", 1) for c in args.engine_container)
    workers = [int(v) for v in args.workers.split(",") if v]
    threads = [int(v) for v in args.request_threads.split(",") if v]
    if bool(workers) != bool(threads):
        parser.error("--workers and --request-threads are swept together: give both or neither")
    base = yaml.safe_load(Path(args.setup).read_text())
    runs = plan_sweeps(
        base,
        known_transports=list(optimistic_load.TRANSPORTS),
        deployment=lookup.read_resolved(Path(args.resolved_names)),
        replication=[m for m in args.replication.split(",") if m],
        ttl_s=args.ttl,
        engines=engines,
    )
    if workers:
        runs += plan_worker_sweep(
            base,
            known_transports=list(optimistic_load.TRANSPORTS),
            deployment=lookup.read_resolved(Path(args.resolved_names)),
            workers=workers,
            request_threads=threads,
            engine=engines[0],
        )
    hardware = Hardware(args.physical_cores, args.shared_host == "yes")
    write_plan(runs, Path(args.out), hardware=hardware, engine_containers=containers)
    runnable = sum(1 for r in runs if r.contract is not None)
    print(f"{runnable} runnable, {len(runs) - runnable} skipped (reasons in manifest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
