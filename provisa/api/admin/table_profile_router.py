# Copyright (c) 2026 Kenneth Stott
# Canary: 9a2b4c6d-8e0f-4a1b-2c3d-5e6f7a8b9c0d
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Admin route: profile a registered table with a sampled SELECT."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request

from provisa.api.acting_role import header_role
from provisa.api.admin.table_read import read_as_caller, table_for_steward
from provisa.api.app import state
from provisa.api.errors import ApiError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/tables", tags=["admin", "tables"])

# Requirements: REQ-452, REQ-1921

_SAMPLE_LIMIT = 2000
_PREVIEW_LIMIT = 200


async def _rows(request: Request, table_id: int, x_provisa_role: str | None, limit: int) -> dict:
    """Up to ``limit`` rows of the table, read as the caller (admin/table_read.py): the right
    to register tables in the table's own domain, then the caller's role — its row filters, its
    masks, the columns it may see."""
    if state.model_db is None:
        raise ApiError(503, "profile.database_unavailable", "Database unavailable")
    if state.federation_engine is None:
        raise ApiError(503, "profile.query_engine_unavailable", "Query engine unavailable")
    table = table_for_steward(request, state, table_id)
    # REQ-273: read as the role the request runs as — the one the auth layer established (a
    # held role, a set's meta-role), never the raw header text.
    role_id = header_role(request, x_provisa_role, None)
    if not role_id:
        raise ApiError(
            400,
            "profile.role_header_required",
            "X-Provisa-Role header required to read a table's rows",
        )
    result = await read_as_caller(state, table_id, role_id, limit)
    rows = [dict(zip(result.column_names, row)) for row in result.rows]
    return {
        "columns": list(result.column_names),
        "rows": rows,
        "rowCount": len(rows),
        "draft": bool(table.get("draft")),
    }


@router.post("/{table_id}/profile")
async def profile_table(
    request: Request,
    table_id: int,
    x_provisa_role: str | None = Header(None),
) -> dict:  # REQ-452
    """A sample of the table's rows for its profile, read as the caller."""
    return await _rows(request, table_id, x_provisa_role, _SAMPLE_LIMIT)


@router.post("/{table_id}/preview")
async def preview_table(
    request: Request,
    table_id: int,
    x_provisa_role: str | None = Header(None),
) -> dict:  # REQ-1921
    """The first rows of the table, read as the caller: the table detail's Preview of a draft,
    which no ordinary statement may read."""
    return await _rows(request, table_id, x_provisa_role, _PREVIEW_LIMIT)
