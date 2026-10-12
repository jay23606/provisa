# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A sample answer of an OpenAPI table whose operation declares no response schema (REQ-1924):
the operation is called once with the parameter values the steward gives, and the fields of the
first row it answers with are suggested as the table's columns. Nothing is stored; the steward
accepts or edits each suggestion, and the columns they declare are what the table holds."""

# Requirements: REQ-1924

from __future__ import annotations

from typing import Any

import httpx

#: How long the one sample call may take.
_TIMEOUT = 30.0


def _rows(answer: Any) -> list[dict]:
    """The rows of an answer: the answer itself when it is a list; else the one list of objects
    it holds (``{"result": [...]}``); else the answer as one row."""
    if isinstance(answer, list):
        return [r for r in answer if isinstance(r, dict)]
    if isinstance(answer, dict):
        lists = [v for v in answer.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if len(lists) == 1:
            return lists[0]
        return [answer]
    return []


def _ir_type(value: Any) -> str:
    """The IR type a sampled value suggests: what the JSON value is, nothing guessed beyond it (a
    string stays text, whatever it looks like)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "bigint"
    if isinstance(value, float):
        return "double"
    if isinstance(value, (dict, list)):
        return "json"
    return "text"


def suggested_columns(answer: Any) -> list[tuple[str, str]]:
    """``[(name, IR type), ...]``: the fields of the answer's first row, in its order."""
    rows = _rows(answer)
    return [(name, _ir_type(value)) for name, value in rows[0].items()] if rows else []


async def sample_columns(
    state: Any, source_id: str, table_name: str, params: dict
) -> list[tuple[str, str]]:
    """Call the operation of ``table_name`` once, with ``params`` (its path and query parameters
    by name), and suggest columns from what it answers. A failed call is refused as the remote
    stated it."""
    from provisa.api_source.caller import _apply_auth
    from provisa.api_source.openapi_endpoint import NoOperation, normalize_op_id
    from provisa.core.secrets import resolve_secrets
    from provisa.openapi.mapper import parse_spec

    entry = (getattr(state, "openapi_specs", None) or {}).get(source_id)
    if entry is None:
        raise LookupError(f"the spec of OpenAPI source {source_id!r} is not loaded")
    queries, _ = parse_spec(entry["spec"])
    wanted = normalize_op_id(table_name)
    query = next((q for q in queries if normalize_op_id(q.operation_id) == wanted), None)
    if query is None:
        raise NoOperation(source_id, table_name)
    given = {k: v for k, v in params.items() if v not in (None, "")}
    path = query.path
    for p in query.path_params:
        if p["name"] not in given:
            raise LookupError(
                f"table {table_name!r}: the sample needs path parameter {p['name']!r}"
            )
        path = path.replace("{" + p["name"] + "}", str(given.pop(p["name"])))
    source = state.api_sources[source_id]
    headers: dict[str, str] = dict(source.headers)
    _apply_auth(source.auth, headers, given)
    address = query.server or resolve_secrets(source.base_url)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(address.rstrip("/") + path, params=given or None, headers=headers)
    if resp.is_error:
        raise LookupError(
            f"table {table_name!r}: the sample call answered HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return suggested_columns(resp.json())
