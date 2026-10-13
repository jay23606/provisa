# Copyright (c) 2026 Kenneth Stott
# Canary: 3e9a7c52-8d14-4b0f-b2a6-6c1f5d8e0a47
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Reads of a natively array, struct or map column, marked for the datasource cast (REQ-1965).

Semantic SQL sees such a column as JSON. Its source holds a native value, so every read of it in
the physical statement is wrapped in the marker ``provisa.transpiler.native_json`` resolves, once
the routed backend is known, into that backend's own to-JSON expression. This runs in both
physical rewrites, beside the epoch translation (REQ-1908), so it is derived with the governed
statement and kept with it -- never per request (REQ-1877).
"""

from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp

from provisa.transpiler.native_json import MARKER, NestedColumn, marked_column, native_json_marker

# (schema, physical table) lowercased -> {column name as emitted SQL spells it, lowercased:
# its hidden attributes}, for every registered column that is natively nested at its source.
NestedColumns = dict[tuple[str, str], dict[str, NestedColumn]]


def _resolve(
    col: exp.Column, tables: dict[str, tuple[str, str]], nested_columns: NestedColumns
) -> NestedColumn | None:
    name = col.name.lower()
    if col.table:
        phys = tables.get(col.table.lower())
        return (nested_columns.get(phys) or {}).get(name) if phys else None
    # Unqualified: SQL binds it to the one in-scope table that has it.
    owners = [
        nested_columns[phys][name]
        for phys in set(tables.values())
        if name in nested_columns.get(phys, {})
    ]
    return owners[0] if len(owners) == 1 else None


def _is_write_target(col: exp.Column, scope: exp.Expr) -> bool:
    if isinstance(scope, exp.Insert):
        return col.find_ancestor(exp.Returning) is None  # the target list / ON CONFLICT
    return (
        isinstance(scope, exp.Update) and col.parent in scope.expressions and col.arg_key == "this"
    )


def mark_native_nested_reads(sql: str, nested_columns: NestedColumns) -> str:
    """``sql`` (PostgreSQL dialect, physical table names) with every read of a natively nested
    column wrapped in the datasource-cast marker, aliased to the column's own name in a select
    list so the output column keeps its name.

    A null test keeps the bare column: a NULL value is NULL as JSON, and the source's own null
    test needs no conversion. A column a statement writes is left as written. Idempotent, and a
    statement that names no affected table is returned as given, unparsed."""
    if not nested_columns:
        return sql
    lowered = sql.lower()
    if not any(table in lowered for (_schema, table) in nested_columns):
        return sql
    from provisa.compiler.sql_rewrite import _scope_tables

    tree = sqlglot.parse_one(sql, read="postgres")
    if not any(
        (t.db.lower(), t.name.lower()) in nested_columns for t in tree.find_all(exp.Table) if t.db
    ):
        return sql
    scopes: dict[int, dict[str, tuple[str, str]]] = {}
    changed = False
    for col in list(tree.find_all(exp.Column)):
        if isinstance(col.this, exp.Star):
            continue
        scope = col.find_ancestor(exp.Select, exp.Update, exp.Delete, exp.Insert)
        if scope is None or _is_write_target(col, scope):
            continue
        parent = col.parent
        if isinstance(parent, exp.Is) or marked_column(parent) is not None:
            continue
        tables = scopes.setdefault(id(scope), _scope_tables(scope))
        nested = _resolve(col, tables, nested_columns)
        if nested is None:
            continue
        read = native_json_marker(col.copy(), nested)
        if isinstance(parent, (exp.Select, exp.Returning)):
            col.replace(exp.alias_(read, col.name, quoted=True))
        else:
            col.replace(read)
        changed = True
    return tree.sql(dialect="postgres") if changed else sql


__all__ = ["MARKER", "NestedColumn", "NestedColumns", "mark_native_nested_reads"]
