# Copyright (c) 2026 Kenneth Stott
# Canary: 8d4f2a61-3c7e-4b95-a0d8-e21f6c9b7a53
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the graph explorer draws of a Cypher read (REQ-392): a read returning nodes is answered
inline -- never delivered to a file, whatever the redirect threshold -- bounded by the row limit,
and cut at max nodes counted as distinct nodes, not rows. A read returning rows only ignores max
nodes and goes through the redirect decision as on every surface. The columns the explorer draws
are named from the translation's graph_vars."""

# Requirements: REQ-392, REQ-768, REQ-769, REQ-1949, REQ-1224

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from provisa.api.rest.cypher_drawing import bounded, first_nodes, graph_columns
from provisa.cypher.translator_types import GraphVarKind
from tests.unit.test_cache_before_route import pipe  # noqa: F401  (the shared pipeline fixture)

_QUERY = "MATCH (o:Orders) RETURN o.id AS id"


def _node(i: int) -> dict:
    return {"id": i, "label": "Customers", "tableLabel": "Customers", "properties": {"id": i}}


@pytest.fixture
def graph(pipe, monkeypatch):  # noqa: F811
    """The pipeline stand-in, with the redirect decision recorded: a drawn read must never reach
    it, a read of rows must."""
    import provisa.executor.redirect as redirect

    state = pipe.state
    state.cypher_label_maps = {}
    state.schema_build_cache = {"tables": None, "relationships": None, "column_types": None}
    state.contexts["analyst"].aggregate_columns[1] = [("id", "integer")]
    pipe.redirect_asked = []
    monkeypatch.setattr(
        redirect,
        "auto_delivery_for_buffered",
        lambda role, *a: pipe.redirect_asked.append(role),  # None: inline, as when disabled
    )
    return pipe


def _drawn(monkeypatch, *, nodes_of_row, row_limit: int) -> None:
    """The read draws a node column, each row holding ``nodes_of_row(row id)``; the row limit is
    ``row_limit``."""
    import provisa.api.rest.cypher_drawing as drawing
    import provisa.api.rest.cypher_router as cr
    import provisa.core.limits as limits
    import provisa.cypher.assembler as assembler

    async def _registered(rows, db):
        return None

    monkeypatch.setattr(drawing, "graph_columns", lambda gv: {"c": "node"})
    monkeypatch.setattr(limits, "default_row_limit", lambda: row_limit)
    monkeypatch.setattr(
        cr,
        "_serialize_rows",
        lambda rows, *_: (["c"], [{"c": nodes_of_row(r["id"])} for r in rows]),
    )
    monkeypatch.setattr(assembler, "register_node_ids", _registered)
    monkeypatch.setattr(assembler, "register_rel_ids", _registered)


async def _ask(graph, rows: int, max_nodes: int | None):
    from provisa.api.rest.cypher_router import CypherRequest, cypher_query

    graph.state.federation_engine._rows_for = lambda sql, params: [(i,) for i in range(rows)]
    request = MagicMock()
    request.state.role = "analyst"
    request.headers = {}
    body = CypherRequest(query=_QUERY, max_nodes=max_nodes)
    resp = await cypher_query(body, request, query_id=None, x_provisa_stats=None)
    return resp.status_code, json.loads(bytes(resp.body))


@pytest.mark.asyncio
async def test_many_rows_over_few_nodes_are_drawn_whole_inline(graph, monkeypatch):
    """1,160 rows over 300 distinct nodes, max nodes 1,000: every row, inline, nothing cut, and the
    redirect threshold never asked."""
    _drawn(monkeypatch, nodes_of_row=lambda i: _node(i % 300), row_limit=5000)
    status, body = await _ask(graph, rows=1160, max_nodes=1000)
    assert status == 200, body
    assert len(body["rows"]) == 1160 and "truncated" not in body and "redirect" not in body
    assert graph.redirect_asked == []


@pytest.mark.asyncio
async def test_distinct_nodes_past_max_nodes_cut_the_drawing(graph, monkeypatch):
    _drawn(monkeypatch, nodes_of_row=lambda i: [_node(i), _node(i + 1000)], row_limit=5000)
    status, body = await _ask(graph, rows=50, max_nodes=20)
    assert status == 200, body
    assert len(body["rows"]) == 10 and body["truncated"] is True  # two new nodes a row


@pytest.mark.asyncio
async def test_a_drawing_past_the_row_limit_is_cut_at_it(graph, monkeypatch):
    _drawn(monkeypatch, nodes_of_row=lambda i: _node(i % 3), row_limit=40)
    status, body = await _ask(graph, rows=41, max_nodes=None)
    assert status == 200, body
    assert len(body["rows"]) == 40 and body["truncated"] is True
    assert "LIMIT 41" in graph.state.federation_engine.statements[-1][1]


@pytest.mark.asyncio
async def test_max_nodes_above_the_row_limit_is_held_to_it(graph, monkeypatch):
    _drawn(monkeypatch, nodes_of_row=_node, row_limit=30)
    status, body = await _ask(graph, rows=30, max_nodes=500)
    assert status == 200, body
    assert len(body["rows"]) == 30 and "truncated" not in body


@pytest.mark.asyncio
async def test_a_rows_only_read_ignores_max_nodes_and_meets_the_redirect_rule(graph):
    status, body = await _ask(graph, rows=5, max_nodes=2)
    assert status == 200, body
    assert body["graph_columns"] == {}
    assert len(body["rows"]) == 5 and "truncated" not in body
    assert graph.redirect_asked == ["analyst"]  # the threshold decides, as on every surface
    assert "LIMIT 3" not in graph.state.federation_engine.statements[-1][1]  # no drawing bound


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


def test_first_nodes_counts_a_relationships_ends_and_a_paths_nodes_once():
    a, b, c = _node(1), _node(2), _node(3)
    edge = {"identity": "e", "type": "R", "startNode": a, "endNode": b, "properties": {}}
    rows = [
        {"r": edge},  # a, b
        {"p": {"nodes": [a, b], "edges": [edge]}},  # nothing new
        {"n": c},  # c: the third
    ]
    assert first_nodes(rows, 3) == (rows, False)
    assert first_nodes(rows, 2) == (rows[:2], True)
