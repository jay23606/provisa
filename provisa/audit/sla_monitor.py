# Copyright (c) 2026 Kenneth Stott
# Canary: 0f08b18c-d19c-4b5a-ad91-dbac5bc1fa32
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Service-level monitoring (REQ-074, REQ-506).

The record of every served query's latency and outcome is the audit row the one audit writer
stores for it (``query_audit_log``: ``duration_ms``, ``status_code``, ``logged_at``). Nothing is
written a second time for monitoring: the summary and the breach check read those rows, so the
service level and the audit trail cannot disagree.

The two limits are operator settings (``sla.p99_limit_ms``, ``sla.availability_min_pct``), read
when a window is evaluated. A breach is stored in ``sla_breach_log``: a row is opened when a
measure goes past its limit and closed when it comes back, so a sustained breach is one row with
a duration and the history survives a restart.

The audit rows are in the org's own store, written by the node that served the query. With
regions, a node's store is its region's, so a summary is of the queries the node's region served.

An empty window has no percentile and no availability. It is reported as empty and is never a
pass or a breach.
"""

# Requirements: REQ-074, REQ-506

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select, update

from provisa.core.schema_org import query_audit_log, sla_breach_log

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from provisa.core.database import Connection

log = logging.getLogger(__name__)

# A request counts as "available" when its status is below the HTTP 5xx server-error band.
_HTTP_SERVER_ERROR = 500

#: The window a service level is evaluated over, and how often it is evaluated.
WINDOW_HOURS = 1
EVALUATE_MINUTES = 5

LATENCY = "latency"
AVAILABILITY = "availability"

JOB_ID = "sla:evaluate"


@dataclass(frozen=True)
class SlaLimits:
    """The service-level limits in force."""

    p99_limit_ms: int
    availability_min_pct: float


def sla_limits() -> SlaLimits:
    """The limits the operator has set (REQ-506), as they are now."""
    from provisa.core import settings_registry

    return SlaLimits(
        p99_limit_ms=int(settings_registry.value("sla.p99_limit_ms")),
        availability_min_pct=float(settings_registry.value("sla.availability_min_pct")),
    )


def _percentile_cont(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated continuous percentile, matching Postgres percentile_cont."""
    n = len(sorted_vals)
    rank = p * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


async def get_sla_summary(  # REQ-074, REQ-506
    conn: "Connection",
    tenant_id: str | None,
    hours: int = WINDOW_HOURS,
    *,
    now: datetime | None = None,
) -> dict:
    """Latency percentiles and availability of the queries ``tenant_id`` was served in the last
    ``hours``, from their audit rows. The read is bounded by the audit table's
    ``(tenant_id, logged_at)`` index."""
    end = now or datetime.now(timezone.utc)
    cutoff = end - timedelta(hours=hours)
    result = await conn.execute_core(
        select(query_audit_log.c.duration_ms, query_audit_log.c.status_code).where(
            query_audit_log.c.tenant_id == tenant_id,
            query_audit_log.c.logged_at >= cutoff,
            query_audit_log.c.logged_at <= end,
        )
    )
    rows = result.fetchall()
    count = len(rows)
    window = {"window_start": cutoff.isoformat(), "window_end": end.isoformat(), "count": count}
    if count == 0:
        return {
            **window,
            "avg_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "availability_pct": None,
        }
    durations = sorted(float(r.duration_ms) for r in rows)
    available = sum(1 for r in rows if r.status_code < _HTTP_SERVER_ERROR)
    return {
        **window,
        "avg_ms": sum(durations) / count,
        "p50_ms": _percentile_cont(durations, 0.50),
        "p95_ms": _percentile_cont(durations, 0.95),
        "p99_ms": _percentile_cont(durations, 0.99),
        "availability_pct": 100.0 * available / count,
    }


def breached(summary: dict, limits: SlaLimits) -> dict[str, tuple[float, float]]:  # REQ-506
    """The measures of ``summary`` past their limit, as ``{kind: (observed, limit)}``. An empty
    window breaches nothing: it has no measure to compare."""
    if not summary["count"]:
        return {}
    found: dict[str, tuple[float, float]] = {}
    if summary["p99_ms"] > limits.p99_limit_ms:
        found[LATENCY] = (summary["p99_ms"], float(limits.p99_limit_ms))
    if summary["availability_pct"] < limits.availability_min_pct:
        found[AVAILABILITY] = (summary["availability_pct"], limits.availability_min_pct)
    return found


def check_sla_breach(summary: dict, limits: SlaLimits | None = None) -> bool:  # REQ-074, REQ-506
    """Whether ``summary`` is past either limit in force."""
    return bool(breached(summary, limits or sla_limits()))


async def record_evaluation(  # REQ-506
    conn: "Connection", tenant_id: str | None, summary: dict, limits: SlaLimits, now: datetime
) -> dict[str, str]:
    """Store what one evaluation found: open a breach row for a measure newly past its limit,
    close the open row of a measure that is back within it. Returns ``{kind: "opened" |
    "ongoing" | "resolved"}`` for the measures that changed or are still in breach.

    An empty window changes nothing: with no queries served there is no evidence the measure
    recovered, so an open breach stays open."""
    if not summary["count"]:
        return {}
    found = breached(summary, limits)
    result = await conn.execute_core(
        select(sla_breach_log.c.id, sla_breach_log.c.kind).where(
            sla_breach_log.c.tenant_id == tenant_id, sla_breach_log.c.resolved_at.is_(None)
        )
    )
    open_rows = {row.kind: row.id for row in result.fetchall()}
    outcome: dict[str, str] = {}
    for kind, (observed, limit) in found.items():
        if kind in open_rows:
            # The row keeps the worst value seen while the breach lasts.
            await conn.execute_core(
                update(sla_breach_log)
                .where(sla_breach_log.c.id == open_rows[kind])
                .values(last_observed=observed, last_seen_at=now)
            )
            outcome[kind] = "ongoing"
            continue
        await conn.execute_core(
            insert(sla_breach_log).values(
                tenant_id=tenant_id,
                kind=kind,
                observed=observed,
                last_observed=observed,
                limit_value=limit,
                window_start=datetime.fromisoformat(summary["window_start"]),
                window_end=datetime.fromisoformat(summary["window_end"]),
                started_at=now,
                last_seen_at=now,
            )
        )
        outcome[kind] = "opened"
    for kind, row_id in open_rows.items():
        if kind not in found:
            await conn.execute_core(
                update(sla_breach_log).where(sla_breach_log.c.id == row_id).values(resolved_at=now)
            )
            outcome[kind] = "resolved"
    return outcome


async def list_breaches(conn: "Connection", tenant_id: str | None, limit: int = 50) -> list[dict]:
    """The breach history, newest first (REQ-506)."""
    result = await conn.execute_core(
        select(sla_breach_log)
        .where(sla_breach_log.c.tenant_id == tenant_id)
        .order_by(sla_breach_log.c.started_at.desc(), sla_breach_log.c.id.desc())
        .limit(limit)
    )
    return [
        {
            "kind": row.kind,
            "observed": row.observed,
            "last_observed": row.last_observed,
            "limit": row.limit_value,
            "started_at": row.started_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }
        for row in result.fetchall()
    ]


async def evaluate_org(org_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Evaluate one org's last window against the limits and store the outcome (REQ-506). A
    breach that opens is logged at WARNING; the history is ``ops.sla_breach_log``."""
    from provisa.api.app import state
    from provisa.core.request_context import reset_current_org, set_current_org

    token = set_current_org(org_id)
    try:
        record_db = state.record_db
        assert record_db is not None, "the org's record store is bound with its runtime"
        at = now or datetime.now(timezone.utc)
        limits = sla_limits()
        async with record_db.acquire() as conn:
            summary = await get_sla_summary(conn, org_id, now=at)
            outcome = await record_evaluation(conn, org_id, summary, limits, at)
    finally:
        reset_current_org(token)
    for kind, change in outcome.items():
        if change == "opened":
            log.warning(
                "service level breached for org %s: %s (window of %d queries)",
                org_id,
                kind,
                summary["count"],
            )
    return {"summary": summary, "outcome": outcome}


def sla_job_id(org_id: str) -> str:
    return f"{JOB_ID}:org_{org_id}"


def register_org_sla(scheduler: "AsyncIOScheduler", org_id: str) -> None:
    """Evaluate ``org_id``'s service level every EVALUATE_MINUTES (REQ-506). A job already held
    is kept, so its clock is not restarted when the org's model is reloaded."""
    from apscheduler.triggers.interval import IntervalTrigger

    job_id = sla_job_id(org_id)
    if scheduler.get_job(job_id) is not None:
        return
    scheduler.add_job(
        evaluate_org,
        trigger=IntervalTrigger(minutes=EVALUATE_MINUTES),
        args=[org_id],
        id=job_id,
        name=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
