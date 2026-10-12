# Copyright (c) 2026 Kenneth Stott
# Canary: 593c7db7-6589-42d1-9c01-ce4eed3290bb
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A save keeps what the source says of a table's parameters (REQ-1986): how each reaches the
source and whether the source requires it are recorded at registration. A steward sets only
``required_by_steward``; a save that changes either recorded value of an existing parameter is
refused."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

if TYPE_CHECKING:
    from provisa.core.database import Connection


async def source_parameter_refusal(conn: "Connection", model: Any) -> str | None:
    """Why this save of ``model`` may not be made, or None: it changes how a stored parameter
    reaches the source, or whether the source requires it."""
    from provisa.api.admin._hiding_guard import stored_table
    from provisa.core.schema_org import table_columns as tc

    stored = await stored_table(conn, model)
    if stored is None:
        return None
    rows = (
        await conn.execute_core(
            select(tc.c.column_name, tc.c.native_filter_type, tc.c.native_filter_required).where(
                tc.c.table_id == stored["id"], tc.c.native_filter_type.is_not(None)
            )
        )
    ).fetchall()
    recorded = {r[0]: (r[1], r[2]) for r in rows}
    for col in model.columns:
        was = recorded.get(col.name)
        if was is None:
            continue
        kind, required = was
        if col.native_filter_type != kind:
            return (
                f"Parameter {col.name!r} of {model.table_name!r} reaches the source as {kind}, "
                "as the source describes it; that cannot be changed."
            )
        if required is not None and col.native_filter_required != required:
            return (
                f"Parameter {col.name!r} of {model.table_name!r}: whether the source requires it "
                "is recorded from the source and cannot be changed; a steward makes a parameter "
                "required with required_by_steward."
            )
    return None
