# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""The data-quality checkers of a table (REQ-1443): every checker table whose contract scans it.
A contract names the dataset it scans (:func:`provisa.dq.contract.contract_dataset`, the one
parser), and a table is that dataset when its own pgwire name
(:func:`provisa.dq.contract.meta_dataset`) is the same, so the reverse of the checker's target is
read through the same function, never a second parser."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from provisa.dq.contract import CHECKERS, contract_dataset
from provisa.dq.results import DQ_WATERMARK_COLUMN, results_sa_table

#: A scan's outcome is its worst check's, in this order.
_SEVERITY = ("error", "fail", "warn", "pass", "skipped")


def scan_outcome(outcomes: list[str]) -> str:
    """One scan's outcome: its worst check's (an error over a failure, a failure over a
    warning...). A check outcome outside the checkers' envelope is refused by name."""
    unknown = sorted(set(outcomes) - set(_SEVERITY))
    if unknown:
        raise ValueError(f"scan outcome(s) {unknown} are none of {list(_SEVERITY)}")
    return min(outcomes, key=_SEVERITY.index)


async def last_scan(conn: Any, relation: str) -> tuple[str, datetime] | None:
    """The outcome and time of the last scan in a checker table's result relation; None before
    its first scan (the relation is created empty when the table is registered)."""
    results = results_sa_table(relation)
    stamp = results.c[DQ_WATERMARK_COLUMN]
    latest = select(func.max(stamp)).scalar_subquery()
    rows = (
        await conn.execute_core(select(results.c.outcome, stamp).where(stamp == latest))
    ).fetchall()
    if not rows:
        return None
    return scan_outcome([r[0] for r in rows]), rows[0][1]


async def checkers_of(conn: Any, dataset: str) -> list[dict[str, Any]]:
    """``[{table_id, table_name, source_id, domain_id, outcome, scan_time}]`` of every checker
    table whose contract scans ``dataset``, in table order; outcome and scan time are None before
    a checker's first scan."""
    from provisa.core.schema_org import registered_tables as rt
    from provisa.core.schema_org import sources

    found = (
        await conn.execute_core(
            select(
                rt.c.id,
                rt.c.table_name,
                rt.c.alias,
                rt.c.source_id,
                rt.c.domain_id,
                rt.c.dq_contract,
                sources.c.type,
            )
            .join(sources, sources.c.id == rt.c.source_id)
            .where(sources.c.type.in_(sorted(CHECKERS)), rt.c.dq_contract.is_not(None))
            .order_by(rt.c.id)
        )
    ).fetchall()
    out: list[dict[str, Any]] = []
    for table_id, relation, alias, source_id, domain_id, contract, checker in found:
        if contract_dataset(contract, checker) != dataset:
            continue
        scan = await last_scan(conn, relation)
        out.append(
            {
                "table_id": table_id,
                # The steward's name: registration keeps it as the alias of a checker table, whose
                # own name is its result relation's (provisa.dq.registration).
                "table_name": alias,
                "source_id": source_id,
                "domain_id": domain_id,
                "outcome": scan[0] if scan else None,
                "scan_time": scan[1] if scan else None,
            }
        )
    return out
