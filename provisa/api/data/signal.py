# Copyright (c) 2026 Kenneth Stott
# Canary: da743047-ae96-4061-9189-d90b3a12ff09
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The receiver of the ``signal`` change signal: an HTTP webhook (REQ-1149).

An upstream system that changed a source says so, with no rows: ``POST
/data/sources/{source_id}/signal``, or ``?table=schema.table`` for one table. Each table of the
source on the ``signal`` change signal (its own, else its source's) is then treated as written:
what is held of its rows stops being served and a build of its replica is asked for, through the
durable build request every change to a replicated table makes (``table_written``). A
load-protected table's build waits for its off-peak window (REQ-1141).

The caller acts as a role that holds the write right and reaches the domain of every table it
signals: a signal is a change to the data, and admitted as one.
"""

# Requirements: REQ-1149, REQ-929

from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from provisa.api.errors import ApiError

router = APIRouter(prefix="/data", tags=["data"])

SIGNAL = "signal"


@router.post("/sources/{source_id}/signal", status_code=202)
async def receive_signal(
    source_id: str,
    raw_request: Request,
    table: str | None = Query(default=None),
    x_provisa_role: str | None = Header(default=None),
) -> JSONResponse:
    """Mark the source's ``signal`` tables (or the one ``table`` names) changed; answers with
    the tables whose builds were asked for."""
    from provisa.api.acting_role import acting_role
    from provisa.api.app import state
    from provisa.api.data.table_written import after_table_written
    from provisa.federation.registry_view import registered_sources
    from provisa.security.rights import Capability, has_capability, reaches_domain, require_role

    role_id = acting_role(raw_request, x_provisa_role, None, "org_admin")
    role = require_role(state.roles, role_id)
    if not has_capability(role, Capability.WRITE):
        raise ApiError(
            403,
            "data.signal_not_admitted",
            f"Role {role_id!r} lacks the write right a change signal needs",
            role=role_id,
        )
    source = next((s for s in await registered_sources(state) if s.id == source_id), None)
    if source is None:
        raise ApiError(
            404, "data.signal_source_not_found", f"Source {source_id!r} not found", source=source_id
        )

    def _signalled(t: dict) -> bool:
        signal = t["change_signal"] if t["change_signal"] is not None else source.change_signal
        return signal == SIGNAL

    candidates = [t for t in state.tables if t["source_id"] == source_id]
    if table is not None:
        candidates = [t for t in candidates if f"{t['schema_name']}.{t['table_name']}" == table]
        if not candidates:
            raise ApiError(
                404,
                "data.signal_table_not_found",
                f"Source {source_id!r} has no registered table {table!r}",
                source=source_id,
                table=table,
            )
    signalled = [t for t in candidates if _signalled(t)]
    if not signalled:
        raise ApiError(
            409,
            "data.signal_not_declared",
            f"No table of source {source_id!r}"
            + (f" named {table!r}" if table is not None else "")
            + " is on the signal change signal: nothing is refreshed by a signal",
            source=source_id,
        )
    for t in signalled:
        if not reaches_domain(role.get("domain_access"), t["domain_id"]):
            raise ApiError(
                403,
                "data.signal_not_admitted",
                f"Role {role_id!r} does not reach domain {t['domain_id']!r} of table "
                f"{t['schema_name']}.{t['table_name']}",
                role=role_id,
            )
    for t in signalled:
        await after_table_written(
            state, table_id=t["id"], table_name=t["table_name"], source_id=source_id
        )
    return JSONResponse(
        status_code=202,
        content={"signalled": [f"{t['schema_name']}.{t['table_name']}" for t in signalled]},
    )
