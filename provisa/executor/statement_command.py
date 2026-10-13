# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A call of a statement command (REQ-2001): its statement through the one pipeline
(``_govern_and_route`` then ``_execute_plan``) as the caller's role, so it is governed as any
statement the caller sends; its arguments bound in declared order, never in the text. What the
statement declares is :mod:`provisa.core.statement_declaration`."""

# Requirements: REQ-2001

from __future__ import annotations

from typing import Any

from provisa.core.statement_declaration import StatementCommandRefused, declared


async def run(fn: dict, args: dict, state: Any, role_id: str | None) -> list[dict]:
    """One call of a statement command: its statement through the one pipeline as the caller's
    role, the call's arguments bound in declared order (REQ-2001)."""
    from provisa.executor.serialize import _convert_value
    from provisa.pgwire._pipeline import _execute_plan, _govern_and_route

    if role_id is None:
        raise StatementCommandRefused(
            fn["name"], "a statement command runs as a role; none is bound"
        )
    names = [a["name"] for a in fn.get("arguments") or []]
    found = declared(fn["name"], fn.get("binding") or {}, names)
    params = [args[n] for n in names]
    plan = await _govern_and_route(found.sql, role_id, params=params or None)
    result = await _execute_plan(plan, state)
    if found.kind == "mutation" and not found.returns_rows:
        # The write's count, as pgwire's command tag reads it (server._write_tag).
        count = result.rowcount if result.rowcount is not None else len(result.rows)
        return [{"rows_affected": count}]
    cols = result.column_names
    return [{c: _convert_value(v) for c, v in zip(cols, r)} for r in result.rows]
