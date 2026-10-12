# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A live-only source's part of a statement the engine answers (REQ-2000).

A live-only source type (``core.source_registry.LIVE_ONLY_TYPES``) has no replica. When a statement
reading one of its tables is answered by the engine -- it joins another source, or computes over
one of the table's columns, as a mask does -- the table's part of the statement is cut from it and
read from the source for that statement alone, through the source's direct driver, and its rows
handed to the engine as a search table's are. The part is the table's columns, the conditions of
the statement on the table alone (its row rules among them), and, where the table is read alone
in its SELECT, that SELECT's similarity ordering and LIMIT. A part with no condition and no top-k
would read the whole table, a replica by another name, and is refused, as is a part the source's
driver cannot state exactly: never replicated.
"""

# Requirements: REQ-2000

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

_SIMILARITY = "cosine_similarity"


class LiveReadRefused(ValueError):
    """A live-only table's part of a statement that cannot be read live, by the table's name."""

    def __init__(self, table: str, reason: str) -> None:
        super().__init__(f"Table {table!r} is read live from its source: {reason}")
        self.table = table
        self.reason = reason


@dataclass(frozen=True)
class Part:
    """The statement's read of one live-only table: a single-table SELECT in PostgreSQL text."""

    table: dict
    sql: str


def live_only_tables(state: Any, table_ids: tuple[int, ...]) -> list[dict]:
    """The tables the statement reads whose source type is live-only, except search tables (read
    under their arguments, ``api.data.materialization``)."""
    from provisa.core.source_registry import is_live_only

    ids = set(table_ids)
    types = getattr(state, "source_types", None) or {}
    return [
        t
        for t in getattr(state, "tables", None) or []
        if t.get("id") in ids
        and is_live_only(types.get(t["source_id"]))
        and not t.get("query_template")
    ]


def _joins(select: exp.Select) -> list[exp.Join]:
    return list(select.args.get("joins") or [])


def _from_table(select: exp.Select) -> exp.Expr | None:
    from_ = select.args.get("from") or select.args.get("from_")
    return from_.this if from_ is not None else None


def _reads(select: exp.Select, name: str) -> list[tuple[exp.Table, exp.Join | None]]:
    """Each place ``select`` reads the table ``name`` directly: in its FROM (no join) or a JOIN."""
    found: list[tuple[exp.Table, exp.Join | None]] = []
    first = _from_table(select)
    if isinstance(first, exp.Table) and first.name == name:
        found.append((first, None))
    for join in _joins(select):
        if isinstance(join.this, exp.Table) and join.this.name == name:
            found.append((join.this, join))
    return found


def _nullable(select: exp.Select, join: exp.Join | None) -> bool:
    """Whether the table read at ``join`` (None: the FROM) is on the side an outer join pads."""
    sides = [(j.side or "").upper() for j in _joins(select)]
    if "FULL" in sides:
        return True
    if join is None:
        return "RIGHT" in sides
    return (join.side or "").upper() == "LEFT"


def _conjuncts(node: exp.Expr | None) -> list[exp.Expr]:
    if node is None:
        return []
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    return [node]


def _alone(node: exp.Expr, alias: str, single: bool) -> bool:
    """Whether ``node`` reads the table under ``alias`` and nothing else, with no parameter (the
    engine binds those) and no subquery."""
    columns = list(node.find_all(exp.Column))
    if not columns:
        return False
    if node.find(exp.Placeholder) is not None or node.find(exp.Parameter) is not None:
        return False
    if node.find(exp.Select) is not None:
        return False
    return all(c.table == alias or (not c.table and single) for c in columns)


def _unqualified(node: exp.Expr) -> exp.Expr:
    copy = node.copy()
    for column in copy.find_all(exp.Column):
        column.set("table", None)
    return copy


def _top_k(select: exp.Select) -> tuple[exp.Expr, exp.Expr] | None:
    """The SELECT's ``ORDER BY cosine_similarity(...) DESC`` and LIMIT, when it reads one table
    with nothing between them and the rows it reads."""
    if _joins(select):
        return None
    for part in ("group", "having", "distinct", "windows", "offset"):
        if select.args.get(part):
            return None
    if select.find(exp.AggFunc) is not None:
        return None
    order, limit = select.args.get("order"), select.args.get("limit")
    if order is None or limit is None or len(order.expressions) != 1:
        return None
    ordered = order.expressions[0]
    call = ordered.this
    if not (
        isinstance(call, exp.Anonymous)
        and str(call.this).lower() == _SIMILARITY
        and ordered.args.get("desc")
    ):
        return None
    return _unqualified(ordered), limit.expression


def cut(sql: str, table: dict) -> Part:
    """``table``'s part of the governed physical ``sql``, or :class:`LiveReadRefused`."""
    name = table["table_name"]
    tree = sqlglot.parse_one(sql, read="postgres")
    places = [
        (select, tbl, join)
        for select in tree.find_all(exp.Select)
        for tbl, join in _reads(select, name)
    ]
    if len(places) != 1:
        raise LiveReadRefused(name, "the statement reads the table more than once")
    select, tbl, join = places[0]
    alias = tbl.alias_or_name
    single = not _joins(select)
    if _nullable(select, join):
        held = _conjuncts(join.args.get("on")) if join is not None else []
    else:
        # An inner join's ON condition holds as a WHERE condition does.
        held = _conjuncts((select.args.get("where") or exp.Where()).this)
        for inner in _joins(select):
            if not inner.side:
                held += _conjuncts(inner.args.get("on"))
    pushed = [_unqualified(c) for c in held if _alone(c, alias, single)]
    top = _top_k(select) if not _nullable(select, join) else None
    if not pushed and top is None:
        raise LiveReadRefused(
            name, "the statement reads it with no condition, key or top-k, the whole table"
        )
    columns = [
        exp.column(c["column_name"], quoted=True)
        for c in table["columns"]
        if c.get("native_filter_type") is None
    ]
    part = exp.select(*columns).from_(exp.table_(name, quoted=True))
    if pushed:
        part = part.where(exp.and_(*pushed))
    if top is not None:
        ordered, limit = top
        part = part.order_by(ordered).limit(limit)
    return Part(table, part.sql(dialect="postgres"))


async def read(state: Any, part: Part) -> Any:
    """``part`` read from its source through the source's direct driver, as the rows a search
    table lands (``mongodb.pipeline_table.PipelineRead``)."""
    from provisa.core.ir_types import to_ir
    from provisa.mongodb.pipeline_table import PipelineRead

    table = part.table
    driver = state.source_pools.get(table["source_id"])
    reason = await driver.reason(part.sql, table)
    if reason is not None:
        raise LiveReadRefused(table["table_name"], reason)
    result = await driver.execute(part.sql)
    names = result.column_names
    columns = {c["column_name"]: c for c in table["columns"]}
    return PipelineRead(
        rows=[dict(zip(names, row)) for row in result.rows],
        columns=[(n, to_ir(columns[n]["data_type"])) for n in names],
    )
