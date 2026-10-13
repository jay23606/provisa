# Copyright (c) 2026 Kenneth Stott
# Canary: 5b1e7c3a-2f84-4d69-9a0e-c7d3f18b6e42
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the graph explorer draws of a Cypher read (REQ-392): one that returns nodes,
relationships or paths is answered inline, bounded by the row limit, and cut at the explorer's max
nodes -- distinct nodes, which a row can repeat. A read that returns none of them is rows, answered
as any other surface answers them. Leaf module (no route handlers).
"""

# Requirements: REQ-392, REQ-768, REQ-769, REQ-1949

from __future__ import annotations

from typing import Any

import sqlglot
import sqlglot.expressions as exp

from provisa.cypher.translator_types import GraphVarKind

__all__ = ["bounded", "first_nodes", "graph_columns"]

#: The result columns the explorer draws: a node, a relationship, a path, or the pre-built
#: node/relationship JSON of a union subquery. A map or a scalar is a value in a row.
_DRAWN = {
    GraphVarKind.NODE: "node",
    GraphVarKind.EDGE: "edge",
    GraphVarKind.PATH: "path",
    GraphVarKind.PASSTHROUGH: "node",
}


def graph_columns(graph_vars: dict[str, GraphVarKind]) -> dict[str, str]:
    """Each result column the explorer draws, by name: ``node``, ``edge`` or ``path``, from the
    translation's own knowledge of what each returned variable is (``cypher_to_sql``'s
    graph_vars), never from the values. Empty for a read that returns rows only."""
    return {name: _DRAWN[kind] for name, kind in graph_vars.items() if kind in _DRAWN}


def bounded(sql: str, rows: int) -> str:
    """``sql`` asking for at most ``rows`` rows: its own LIMIT where that is the smaller, else
    ``rows``. A LIMIT whose value is not written in the statement is kept, inside a SELECT that
    bounds it."""
    tree = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise ValueError(f"not a query: {sql!r}")
    own = tree.args.get("limit")
    value = own.expression if own is not None else None
    if own is not None and not (isinstance(value, exp.Literal) and not value.is_string):
        return f"SELECT * FROM ({sql}) AS _drawn LIMIT {rows}"
    if isinstance(value, exp.Literal) and int(value.name) <= rows:
        return sql
    tree.set("limit", exp.Limit(expression=exp.Literal.number(rows)))
    return tree.sql(dialect="postgres")


def _node_keys(value: Any, into: set[str]) -> None:
    """The identities of the nodes in one serialized value: a node, a relationship's two ends, a
    path's nodes, or any of them nested in a list or map."""
    if isinstance(value, list):
        for item in value:
            _node_keys(item, into)
    elif isinstance(value, dict):
        if "label" in value and "properties" in value and "startNode" not in value:
            into.add(f"{value['label']}:{value['id']}")
            return
        for item in value.values():
            _node_keys(item, into)


def first_nodes(rows: list[Any], max_nodes: int) -> tuple[list[Any], bool]:
    """The rows, in order, whose nodes number at most ``max_nodes`` distinct, and whether a row was
    left out because its nodes would have passed it."""
    seen: set[str] = set()
    for i, row in enumerate(rows):
        found: set[str] = set()
        _node_keys(row, found)
        new = found - seen
        if len(seen) + len(new) > max_nodes:
            return rows[:i], True
        seen |= new
    return rows, False
