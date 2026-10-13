# Copyright (c) 2026 Kenneth Stott
# Canary: 8d4f2a61-3c7e-4b95-a0d8-e21f6c9b7a53
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the graph explorer draws of a Cypher read (REQ-392): a read returning nodes is bounded at
the explorer's max_nodes + 1 rows and answered with the first max_nodes, said as cut when the row
after them came back; a read returning rows only ignores max_nodes. The columns the explorer draws
are named from the translation's graph_vars."""

# Requirements: REQ-392, REQ-768, REQ-769

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from provisa.api.rest.cypher_drawing import bounded, graph_columns, was_cut
from provisa.cypher.translator_types import GraphVarKind
from tests.unit.test_cache_before_route import pipe  # noqa: F401  (the shared pipeline fixture)


@pytest.fixture
def graph(pipe):  # noqa: F811
    state = pipe.state
    state.cypher_label_maps = {}
    state.schema_build_cache = {"tables": None, "relationships": None, "column_types": None}
    state.contexts["analyst"].aggregate_columns[1] = [("id", "integer")]
    return pipe


async def _ask(graph, query: str, rows: int, max_nodes: int | None):
    from provisa.api.rest.cypher_router import CypherRequest, cypher_query

    graph.state.federation_engine._rows_for = lambda sql, params: [(i,) for i in range(rows)]
    request = MagicMock()
    request.state.role = "analyst"
    request.headers = {}
    body = CypherRequest(query=query, max_nodes=max_nodes)
    resp = await cypher_query(body, request, query_id=None, x_provisa_stats=None)
    return resp.status_code, json.loads(bytes(resp.body))


@pytest.mark.asyncio
async def test_a_rows_only_read_ignores_max_nodes(graph):
    status, body = await _ask(graph, "MATCH (o:Orders) RETURN o.id AS id", rows=5, max_nodes=2)
    assert status == 200, body
    assert body["graph_columns"] == {}
    assert len(body["rows"]) == 5 and "truncated" not in body
    sql = graph.state.federation_engine.statements[-1][1]
    assert "LIMIT 3" not in sql


@pytest.mark.asyncio
async def test_max_nodes_above_the_drawing_ceiling_is_clamped_to_it(graph, monkeypatch):
    import provisa.api.rest.cypher_drawing as drawing

    monkeypatch.setattr(drawing, "drawing_ceiling", lambda: 3)
    monkeypatch.setattr(drawing, "graph_columns", lambda gv: {"id": "node"})  # a drawn column
    status, body = await _ask(graph, "MATCH (o:Orders) RETURN o.id AS id", rows=9, max_nodes=50)
    assert status == 200, body
    assert len(body["rows"]) == 3 and body["truncated"] is True
    assert "LIMIT 4" in graph.state.federation_engine.statements[-1][1]


@pytest.mark.asyncio
async def test_a_drawn_read_is_bounded_and_cut_at_max_nodes(graph, monkeypatch):
    import provisa.api.rest.cypher_drawing as drawing

    monkeypatch.setattr(drawing, "drawing_ceiling", lambda: 10)
    monkeypatch.setattr(drawing, "graph_columns", lambda gv: {"id": "node"})
    status, body = await _ask(graph, "MATCH (o:Orders) RETURN o.id AS id", rows=3, max_nodes=2)
    assert status == 200, body
    assert len(body["rows"]) == 2 and body["truncated"] is True
    assert "LIMIT 3" in graph.state.federation_engine.statements[-1][1]


@pytest.mark.asyncio
async def test_a_drawn_read_within_max_nodes_is_not_cut(graph, monkeypatch):
    import provisa.api.rest.cypher_drawing as drawing

    monkeypatch.setattr(drawing, "drawing_ceiling", lambda: 10)
    monkeypatch.setattr(drawing, "graph_columns", lambda gv: {"id": "node"})
    status, body = await _ask(graph, "MATCH (o:Orders) RETURN o.id AS id", rows=2, max_nodes=2)
    assert status == 200 and len(body["rows"]) == 2 and "truncated" not in body


def test_graph_columns_name_what_the_translation_returns():
    kinds = {
        "n": GraphVarKind.NODE,
        "r": GraphVarKind.EDGE,
        "p": GraphVarKind.PATH,
        "m": GraphVarKind.MAP,
    }
    assert graph_columns(kinds) == {"n": "node", "r": "edge", "p": "path"}


def test_bounded_keeps_a_smaller_limit_and_lowers_a_larger_one():
    assert bounded("SELECT a FROM t LIMIT 2", 5) == "SELECT a FROM t LIMIT 2"
    assert bounded("SELECT a FROM t LIMIT 50", 5) == "SELECT a FROM t LIMIT 5"
    assert bounded("SELECT a FROM t ORDER BY a", 5) == "SELECT a FROM t ORDER BY a LIMIT 5"
    assert bounded("SELECT a FROM t LIMIT $1", 5) == (
        "SELECT * FROM (SELECT a FROM t LIMIT $1) AS _drawn LIMIT 5"
    )


def test_was_cut_by_the_row_after_or_by_the_row_limit():
    assert was_cut(3, 2, [])
    assert not was_cut(2, 2, [])
    assert was_cut(2, 2, ["statement.rows_cut"])
