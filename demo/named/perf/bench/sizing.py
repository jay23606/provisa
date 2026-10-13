# Copyright (c) 2026 Kenneth Stott
# Canary: 72c41358-bee4-461f-91ac-4c37ef6ebbcc
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""A workload sized from a benchmark report (REQ-1911): physical cores, worker processes and
in-flight requests per worker for the workload a setup contract describes (its ``workload``
section: request rate and transport shares; its knobs: fields, filters, rows, joins, source mix
and cacheability).

The workload's requests are drawn from the contract's own seeded request generator, so what is
sized is what a run of the contract would send. Per transport and source: the share of requests,
the mean of each knob, and the share that are response-cache hits (a request that opts in and
equals an earlier opted-in request). A request costs the cell's fitted model at its knob means on
a miss and the cell's measured hit cost on a hit. A transport's Provisa CPU per second, over what
a physical core delivers against that cost (its worker sweep's capacity factor), is the physical
cores it needs.

Any part of the workload the report has no model for is refused by name (``SizingRefused``):
a transport without a worker sweep, a source without a cost model on the transport, a knob the
cell could not cost, a route hint, a replication setting other than the one measured, or cache
hits without cache figures. Nothing is assumed in their place.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import contract_model
import request_mix
from optimistic_load import TRANSPORTS

DEFAULT_DRAWS = 10_000
_STREAM = "sizing"


class SizingRefused(ValueError):
    """A part of the workload the report has no model for; the message names it."""


@dataclass(frozen=True)
class SourceShare:
    source: str
    share: float  # of the transport's requests
    knob_means: dict[str, float]
    hit_share: float  # of this source's requests
    miss_ms: float
    hit_ms: float | None
    cpu_ms: float  # Provisa CPU per request, hits and misses together


@dataclass(frozen=True)
class TransportSizing:
    transport: str
    rate_per_s: float
    sources: tuple[SourceShare, ...]
    cpu_ms: float  # Provisa CPU per request over the transport's sources
    capacity_factor: float
    physical_cores: float  # unrounded
    workers_per_physical_core: float
    in_flight_per_worker: int


@dataclass(frozen=True)
class Sizing:
    rate_per_s: float
    draws: int
    transports: tuple[TransportSizing, ...]
    physical_cores: int
    workers: int
    in_flight_per_worker: int


def _means(specs: Sequence[request_mix.RequestSpec]) -> dict[str, float]:
    n = len(specs)
    return {
        "fields": sum(len(s.columns) for s in specs) / n,
        "filters": sum(len(s.filters) for s in specs) / n,
        "rows": sum(s.rows for s in specs) / n,
        "joins_same": sum(1 for s in specs for j in s.joins if j.kind == "same") / n,
        "joins_cross": sum(1 for s in specs for j in s.joins if j.kind == "cross") / n,
    }


def _hits(specs: Sequence[request_mix.RequestSpec]) -> list[bool]:
    """Per request, whether it is a response-cache hit: it opts in and an equal request opted in
    before it."""
    seen: set[request_mix.RequestSpec] = set()
    out = []
    for s in specs:
        out.append(s.cached and s in seen)
        if s.cached:
            seen.add(s)
    return out


def _source_share(
    transport: str,
    source: str,
    specs: list[request_mix.RequestSpec],
    hits: list[bool],
    total: int,
    cell: Mapping[str, Any],
    setup: contract_model.Setup,
) -> SourceShare:
    name = f"{transport}.{source}"
    if any(s.route is not None for s in specs):
        raise SizingRefused(f"{name}: route hints (direct, federated) are not in the cost model")
    measured = cell["replication"]
    declared = setup.sources[source].replication
    if (declared.setting, declared.ttl_seconds) != (
        measured["replication"],
        measured["ttl_seconds"],
    ):
        raise SizingRefused(
            f"{name}: the workload reads it {declared.setting} (TTL {declared.ttl_seconds} s); "
            f"the run measured it {measured['replication']} (TTL {measured['ttl_seconds']} s)"
        )
    means = _means(specs)
    for knob, reason in cell["not_modelled"].items():
        if abs(means[knob] - cell["baseline_knob_means"][knob]) > 1e-9:
            raise SizingRefused(
                f"{name}: the workload sets {knob} but the run has no cost: {reason}"
            )
    model = cell["provisa_cpu"]
    miss_ms = model["base"] + sum(c * means[k] for k, c in model["per_unit"].items())
    hit_share = sum(hits) / len(specs)
    hit_ms = None
    if hit_share:
        if cell["cache"] is None:
            raise SizingRefused(
                f"{name}: {hit_share:.1%} of the requests hit the response cache, "
                "and the run has no cache figures (cache runs 0 and 1)"
            )
        hit_ms = cell["cache"]["hit_ms"]
    cpu_ms = miss_ms if hit_ms is None else hit_share * hit_ms + (1 - hit_share) * miss_ms
    return SourceShare(source, len(specs) / total, means, hit_share, miss_ms, hit_ms, cpu_ms)


def _transport(
    report: Mapping[str, Any], setup: contract_model.Setup, transport: str, rate: float, draws: int
) -> TransportSizing:
    server = report["server"].get(transport)
    if server is None:
        raise SizingRefused(f"{transport}: the run has no worker sweep for this transport")
    cells = report["transports"].get(transport, {})
    gen = request_mix.RequestGenerator(
        setup, transport, _STREAM, cacheable=TRANSPORTS[transport][1] is not None
    )
    specs = [gen.next() for _ in range(draws)]
    hits = _hits(specs)
    by_source: dict[str, tuple[list[request_mix.RequestSpec], list[bool]]] = {}
    for spec, hit in zip(specs, hits):
        group = by_source.setdefault(spec.source, ([], []))
        group[0].append(spec)
        group[1].append(hit)
    shares = []
    for source, (s_specs, s_hits) in sorted(by_source.items()):
        if source not in cells:
            raise SizingRefused(f"{transport}.{source}: the run has no cost model for this source")
        shares.append(
            _source_share(transport, source, s_specs, s_hits, draws, cells[source], setup)
        )
    cpu_ms = sum(s.share * s.cpu_ms for s in shares)
    return TransportSizing(
        transport=transport,
        rate_per_s=rate,
        sources=tuple(shares),
        cpu_ms=cpu_ms,
        capacity_factor=server["capacity_factor"],
        physical_cores=rate * cpu_ms / 1000 / server["capacity_factor"],
        workers_per_physical_core=server["workers_per_physical_core"],
        in_flight_per_worker=server["in_flight_per_worker"],
    )


def size(
    report: Mapping[str, Any], setup: contract_model.Setup, draws: int = DEFAULT_DRAWS
) -> Sizing:
    """The physical cores, workers and in-flight requests per worker the contract's workload
    needs, by the report's models. One worker count and one in-flight bound serve every
    transport, so each is the largest any of the workload's transports needs."""
    if setup.workload is None:
        raise SizingRefused("workload: the contract describes no workload (rate and transports)")
    rate = setup.workload.rate_per_s
    sized = tuple(
        _transport(report, setup, t, rate * w, draws)
        for t, w in setup.workload.transport_weights.items()
        if w > 0
    )
    cores = math.ceil(sum(t.physical_cores for t in sized))
    return Sizing(
        rate_per_s=rate,
        draws=draws,
        transports=sized,
        physical_cores=cores,
        workers=math.ceil(cores * max(t.workers_per_physical_core for t in sized)),
        in_flight_per_worker=max(t.in_flight_per_worker for t in sized),
    )
