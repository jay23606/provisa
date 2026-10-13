# Copyright (c) 2026 Kenneth Stott
# Canary: 6d2aa202-4005-4d75-8d40-8bc9eddeca83
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The sizing and tuning guide (REQ-1911), generated as Markdown from a benchmark report
(``bench_report.py``), for a solution engineer or a customer.

Tuning: what each setting buys, with the measured figure behind it (worker processes per physical
core, in-flight requests per worker, the response-cache opt-in, live versus replica reads per
source with the break-even, the replica TTL). Sizing, when a contract with a ``workload`` is given:
the physical cores, workers and in-flight requests per worker that workload needs
(``sizing.py``). Every figure names the report statistic it comes from, so the guide is
regenerated from a new run. Figures are in physical cores and state whether the sources and the
load generator shared the server's host. The guide carries no internal label: it may be given to a
customer; the report it is generated from stays internal.

    python sizing_guide.py --report results/sweeps/report.json --out guide.md \\
        [--setup customer.yaml --resolved-names results/resolved-names.json]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import sizing as sz

TITLE = "Provisa sizing and tuning guide"


def _n(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _from(*paths: str) -> str:
    return "From the report: " + ", ".join(f"`{p}`" for p in paths) + "."


def _hardware(report: Mapping[str, Any]) -> list[str]:
    hw = report["hardware"]
    shared = (
        "The sources and the load generator ran on the same host as the server, so they "
        "competed with it for its cores: these figures are a floor."
        if hw["shared_host"]
        else "The sources and the load generator ran on other hosts."
    )
    return [
        "## Measured on",
        "",
        f"A server with {hw['physical_cores']} physical cores. {shared} Every core figure below "
        "is in physical cores, not hardware threads.",
        "",
        _from("hardware.physical_cores", "hardware.shared_host"),
        "",
    ]


def _workers(report: Mapping[str, Any]) -> list[str]:
    server = report["server"]
    if not server:
        return []
    tol = report["tolerance"]
    out = [
        "## Worker processes and in-flight requests",
        "",
        "Each transport was run against the server at every pair of worker processes and "
        "in-flight requests per worker. The setting shown is the fewest workers, then the fewest "
        f"in-flight requests, whose peak throughput is within {tol:.0%} of the best measured. "
        "More workers or in-flight requests than that buy no throughput; fewer leave cores idle. "
        "Requests per second per physical core, against the CPU one request costs on its own, "
        "is the capacity factor sizing uses.",
        "",
        "| Transport | Workers per physical core | In-flight per worker | Peak req/s | p99 ms "
        "| Req/s per physical core | CPU ms per request | Capacity factor |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t, s in server.items():
        out.append(
            f"| {t} | {_n(s['workers_per_physical_core'])} | {s['in_flight_per_worker']} "
            f"| {_n(s['peak_req_per_s'], 0)} | {_n(s['p99_ms'], 1)} "
            f"| {_n(s['peak_req_per_s_per_physical_core'], 0)} "
            f"| {_n(s['provisa_cpu_ms_per_request'], 3)} | {_n(s['capacity_factor'])} |"
        )
    out += [
        "",
        _from(
            "server.<transport>.workers_per_physical_core",
            "server.<transport>.in_flight_per_worker",
            "server.<transport>.peak_req_per_s",
            "server.<transport>.p99_ms",
            "server.<transport>.peak_req_per_s_per_physical_core",
            "server.<transport>.provisa_cpu_ms_per_request",
            "server.<transport>.capacity_factor",
            "tolerance",
        ),
        "",
        "Every measured point:",
        "",
        "| Transport | Workers | In-flight per worker | Peak req/s | p99 ms |",
        "|---|---|---|---|---|",
    ]
    for t, s in server.items():
        for p in s["grid"]:
            out.append(
                f"| {t} | {p['workers']} | {p['request_threads']} "
                f"| {_n(p['peak_req_per_s'], 0)} | {_n(p['p99_ms'], 1)} |"
            )
    out += ["", _from("server.<transport>.grid"), ""]
    return out


def _cells(report: Mapping[str, Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    return [(t, s, c) for t, by in report["transports"].items() for s, c in by.items()]


def _costs(report: Mapping[str, Any]) -> list[str]:
    cells = _cells(report)
    if not cells:
        return []
    out = [
        "## What a request costs",
        "",
        "Provisa CPU per request, uncached: a base cost, plus a cost per selected field, filter, "
        "row returned, same-source join and cross-source join. A dash: the run did not vary "
        "that knob, so it has no cost and a workload that uses it cannot be sized from this run.",
        "",
        "| Transport | Source | Base ms | Per field | Per filter | Per row | Per same-source join "
        "| Per cross-source join | Fit (R²) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t, s, c in cells:
        unit = c["provisa_cpu"]["per_unit"]
        knobs = ("fields", "filters", "rows", "joins_same", "joins_cross")
        per = " | ".join(_n(unit[k], 4) if k in unit else "–" for k in knobs)
        out.append(
            f"| {t} | {s} | {_n(c['provisa_cpu']['base'], 3)} | {per} "
            f"| {_n(c['provisa_cpu']['r2'], 3)} |"
        )
    out += [
        "",
        _from(
            "transports.<transport>.<source>.provisa_cpu.base",
            "transports.<transport>.<source>.provisa_cpu.per_unit",
            "transports.<transport>.<source>.provisa_cpu.r2",
        ),
        "",
    ]
    return out


def _cache(report: Mapping[str, Any]) -> list[str]:
    cells = [(t, s, c) for t, s, c in _cells(report) if c["cache"] is not None]
    if not cells:
        return []
    out = [
        "## The response-cache opt-in",
        "",
        "A request that opts into the response cache and repeats an earlier one is answered "
        "from the cache. What a hit saves is what opting in buys; a request that never repeats "
        "gains nothing from it.",
        "",
        "| Transport | Source | Miss ms | Hit ms | Saved per hit ms |",
        "|---|---|---|---|---|",
    ]
    for t, s, c in cells:
        k = c["cache"]
        out.append(
            f"| {t} | {s} | {_n(k['miss_ms'], 3)} | {_n(k['hit_ms'], 3)} "
            f"| {_n(k['miss_ms'] - k['hit_ms'], 3)} |"
        )
    out += [
        "",
        _from(
            "transports.<transport>.<source>.cache.miss_ms",
            "transports.<transport>.<source>.cache.hit_ms",
        ),
        "",
    ]
    return out


def _break_even(report: Mapping[str, Any]) -> list[str]:
    cells = [(t, s, c) for t, s, c in _cells(report) if c["break_even"] is not None]
    if not cells:
        return []
    out = [
        "## Live or replica reads, and the TTL",
        "",
        "A replica makes each read cheaper and costs a refresh every TTL. Above the break-even "
        "rate a replica costs less CPU (Provisa and the source together) than reading live; "
        "below it, reading live does. The break-even is the refresh's CPU per second over what "
        "one read saves: (refresh CPU s × 1000 / TTL s) / (live ms − replica ms). Doubling the "
        "TTL halves the break-even rate, at the price of data up to twice as old.",
        "",
        "| Transport | Source | Live ms | Replica ms | Refresh CPU s | TTL s | Break-even req/s |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, s, c in cells:
        b = c["break_even"]
        rate = _n(b["requests_per_s"], 1) if b["requests_per_s"] is not None else b["reason"]
        out.append(
            f"| {t} | {s} | {_n(b['live_ms'], 3)} | {_n(b['replica_ms'], 3)} "
            f"| {_n(b['refresh_cpu_s'], 2)} | {b['ttl_s']} | {rate} |"
        )
    out += [
        "",
        _from(
            "transports.<transport>.<source>.break_even.live_ms",
            "transports.<transport>.<source>.break_even.replica_ms",
            "transports.<transport>.<source>.break_even.refresh_cpu_s",
            "transports.<transport>.<source>.break_even.ttl_s",
            "transports.<transport>.<source>.break_even.requests_per_s",
        ),
        "",
    ]
    return out


def _sizing(sized: sz.Sizing) -> list[str]:
    out = [
        "## Sizing this workload",
        "",
        f"{_n(sized.rate_per_s, 0)} requests per second. Each transport's requests were drawn "
        f"from the workload's own description ({sized.draws:,} per transport) and costed by the "
        "models above: a hit at the hit cost, a miss at the source's model for its fields, "
        "filters, rows and joins. Physical cores are the Provisa CPU per second over what a "
        "physical core delivers (its capacity factor).",
        "",
        "| Transport | Req/s | Source | Share | Fields | Filters | Rows | Same-source joins "
        "| Cross-source joins | Cache hits | CPU ms per request |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in sized.transports:
        for s in t.sources:
            m = s.knob_means
            out.append(
                f"| {t.transport} | {_n(t.rate_per_s, 0)} | {s.source} | {s.share:.0%} "
                f"| {_n(m['fields'], 1)} | {_n(m['filters'], 1)} | {_n(m['rows'], 1)} "
                f"| {_n(m['joins_same'], 2)} | {_n(m['joins_cross'], 2)} | {s.hit_share:.0%} "
                f"| {_n(s.cpu_ms, 3)} |"
            )
    out += [
        "",
        "| Transport | CPU ms per request | Capacity factor | Physical cores |",
        "|---|---|---|---|",
    ]
    for t in sized.transports:
        out.append(
            f"| {t.transport} | {_n(t.cpu_ms, 3)} | {_n(t.capacity_factor)} "
            f"| {_n(t.physical_cores)} |"
        )
    out += [
        "",
        f"**{sized.physical_cores} physical cores, {sized.workers} worker processes, "
        f"{sized.in_flight_per_worker} in-flight requests per worker.** One worker count and one "
        "in-flight bound serve every transport, so each is the largest any of the workload's "
        "transports needs.",
        "",
        _from(
            "transports.<transport>.<source>.provisa_cpu",
            "transports.<transport>.<source>.cache.hit_ms",
            "server.<transport>.capacity_factor",
            "server.<transport>.workers_per_physical_core",
            "server.<transport>.in_flight_per_worker",
        ),
        "",
    ]
    return out


def render(report: Mapping[str, Any], sized: sz.Sizing | None = None) -> str:
    lines = [
        f"# {TITLE}",
        "",
        "Generated from a benchmark run. Each figure names the report statistic it comes from; "
        "regenerate the guide from a new run rather than editing it.",
        "",
        *_hardware(report),
        *(_sizing(sized) if sized is not None else []),
        *_workers(report),
        *_costs(report),
        *_cache(report),
        *_break_even(report),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    import lookup
    import optimistic_load
    import setup_contract as sc

    parser = argparse.ArgumentParser(description="The sizing and tuning guide, from a report")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--setup", help="a contract with a workload section to size")
    parser.add_argument(
        "--resolved-names", help="resolved-names.json of the deployment the contract names"
    )
    parser.add_argument("--draws", type=int, default=sz.DEFAULT_DRAWS)
    args = parser.parse_args()
    if bool(args.setup) != bool(args.resolved_names):
        parser.error("--setup and --resolved-names go together")
    report = json.loads(Path(args.report).read_text())
    sized = None
    if args.setup:
        setup = sc.load_setup(
            Path(args.setup),
            known_transports=list(optimistic_load.TRANSPORTS),
            deployment=lookup.read_resolved(Path(args.resolved_names)),
        )
        sized = sz.size(report, setup, args.draws)
    Path(args.out).write_text(render(report, sized))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
