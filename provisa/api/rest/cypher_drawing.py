# Copyright (c) 2026 Kenneth Stott
# Canary: 5b1e7c3a-2f84-4d69-9a0e-c7d3f18b6e42
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the graph explorer draws of a Cypher read (REQ-392): the first ``max_nodes`` rows of one
that returns nodes, relationships or paths, said as cut when there are more. A read that returns
none of them is rows, answered as any other surface answers them; ``max_nodes`` does not apply.
Leaf module (no route handlers).
"""

# Requirements: REQ-392, REQ-768, REQ-769, REQ-1949

from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp

from provisa.core.limits import default_row_limit
from provisa.cypher.translator_types import GraphVarKind

__all__ = ["bounded", "drawing_ceiling", "graph_columns", "was_cut"]

#: The result columns the explorer draws: a node, a relationship, a path, or the pre-built
#: node/relationship JSON of a union subquery. A map or a scalar is a value in a row.
_DRAWN = {
    GraphVarKind.NODE: "node",
    GraphVarKind.EDGE: "edge",
    GraphVarKind.PATH: "path",
    GraphVarKind.PASSTHROUGH: "node",
}


def drawing_ceiling() -> int:
    """The most rows the explorer may ask to draw: the smaller of the row limit
    (``limits.default_row_limit``) and the large-result redirect threshold, the org's where it set
    one (REQ-1349), so a drawing is never cut by the one nor delivered to a file by the other."""
    from provisa.executor.redirect import RedirectConfig

    return min(default_row_limit(), RedirectConfig.from_env().threshold)


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


def was_cut(rows: int, max_nodes: int, warning_codes: list[str]) -> bool:
    """Whether a read bounded at ``max_nodes`` + 1 rows has more than the explorer draws: the row
    after the first ``max_nodes`` came back, or the row limit cut the answer first (REQ-1949)."""
    return rows > max_nodes or "statement.rows_cut" in warning_codes
