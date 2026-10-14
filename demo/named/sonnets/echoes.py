# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The sonnets demo's link_echoes command (REQ-2016): each line's three nearest lines in other
sonnets, written to the echo table.

A python command (``impl_kind: python``), called as ``link_echoes(payload, session)``. It reads the
lines through Provisa as the caller; asks the vector store, for each line's point, for the three
nearest points whose sonnet is another (Qdrant's query by point id, with a filter, limit 3); and
writes what it found to ``sonnets.echo`` through Provisa as the caller, in batches. A line with no
point yet (embed_lines has not run) is refused by name.
"""

from __future__ import annotations

from typing import Any

COLLECTION = "sonnet_lines"
SOURCE = "vectors"
NEAREST = 3
_BATCH = 500


async def _run(sql: str, role_id: str) -> Any:
    from provisa.api.app import state
    from provisa.pgwire._pipeline import _execute_plan, _govern_and_route

    return await _execute_plan(await _govern_and_route(sql, role_id), state)


def _nearest(conn: Any, lines: list[tuple[int, int]]) -> list[tuple[int, int, float]]:
    """(line, echo, score) for each line's nearest points in other sonnets."""
    from qdrant_client import models

    client = conn.client()
    out: list[tuple[int, int, float]] = []
    for line_id, sonnet in lines:
        found = client.query_points(
            COLLECTION,
            query=line_id,
            using="text",
            query_filter=models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="sonnet_number", match=models.MatchValue(value=sonnet)
                    )
                ]
            ),
            limit=NEAREST,
        ).points
        if not found:
            raise ValueError(f"line {line_id} has no point in {COLLECTION}: run embed_lines first")
        out.extend((line_id, int(p.id), float(p.score)) for p in found)
    return out


async def link_echoes(_payload: dict, session: Any) -> list[dict]:
    import asyncio

    from provisa.api.app import state
    from provisa.federation.registry_view import registered_sources
    from provisa.qdrant.fetch import QdrantConnection

    if session.role_id is None:
        raise ValueError("link_echoes runs as a role; none is bound")
    lines = await _run(
        'SELECT id, sonnet_number FROM "sonnets"."line" ORDER BY id', session.role_id
    )
    [source] = [s for s in await registered_sources(state) if s.id == SOURCE]
    echoes = await asyncio.to_thread(
        _nearest, QdrantConnection.from_source(source), [(r[0], r[1]) for r in lines.rows]
    )
    for start in range(0, len(echoes), _BATCH):
        values = ", ".join(f"({a}, {b}, {s!r})" for a, b, s in echoes[start : start + _BATCH])
        await _run(
            f'INSERT INTO "sonnets"."echo" (line_id, echo_line_id, score) VALUES {values}',
            session.role_id,
        )
    return [{"rows_affected": len(echoes)}]
