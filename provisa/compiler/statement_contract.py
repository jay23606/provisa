# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A statement command's contract, derived from its statement against the model (REQ-2001).

The statement is the command's declaration. Resolved against the registered tables (a view
expanded to the tables it reads), it gives: the command's kind, the table it writes and whether it
upserts, the tables it reads, its output columns with their types (or the write's row count), the
types of its arguments, and its column lineage (each written column from the columns it is
computed from). The contract is derived at every schema rebuild; a statement that no longer
resolves (a table or column it names was renamed or dropped) gives a broken contract carrying the
reason. Static -- nothing runs.
"""

# Requirements: REQ-2001

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlglot
import sqlglot.expressions as exp
from sqlglot.errors import OptimizeError, SqlglotError

from provisa.compiler.naming import domain_to_sql_name, stored_relation_names
from provisa.core.statement_declaration import StatementCommandRefused, declared

#: The output of a write without RETURNING: its count.
ROW_COUNT = {"name": "rows_affected", "type": "bigint"}


@dataclass(frozen=True)
class Contract:
    """What a statement command does, derived from its statement (REQ-2001)."""

    statement_hash: str
    kind: str | None = None
    writes: str | None = None  # the written table, as domain.table
    upsert: bool = False  # an INSERT ... ON CONFLICT ... DO UPDATE
    reads: tuple[str, ...] = ()  # the tables read, views expanded, as domain.table
    outputs: tuple[dict[str, str], ...] = ()
    arguments: tuple[dict[str, str], ...] = ()
    # written column -> the read columns (domain.table.column) it is computed from
    lineage: dict[str, list[str]] = field(default_factory=dict)
    # The rows the command writes, as a SELECT naming each written column: the write's edge in
    # the lineage graph (lineage.commands). None for a query or a DELETE.
    write_select: str | None = None
    broken: str | None = None  # why the statement no longer resolves; None when it does

    @property
    def version(self) -> str:
        """The contract's identity: two derivations that say the same have the same version."""
        body = json.dumps(asdict(self), sort_keys=True, default=list)
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "version": self.version}


def statement_hash(sql: str) -> str:
    """The hash of a statement's registered text."""
    return hashlib.sha256(sql.encode()).hexdigest()


class _Relations:
    """The registered tables by every name a statement gives them."""

    def __init__(self, tables: list[dict]) -> None:
        self.by_name: dict[str, dict] = {}
        for t in tables:
            names = stored_relation_names(
                t.get("domain_id") or "", t.get("schema_name") or "", t.get("table_name") or ""
            )
            if t.get("alias"):
                names.append(f"{domain_to_sql_name(t.get('domain_id') or '')}.{t['alias']}")
            for n in names:
                self.by_name[n.lower()] = t

    def resolve(self, table: exp.Table) -> dict | None:
        said = ".".join(p for p in (table.catalog, table.db, table.name) if p)
        return self.by_name.get(said.lower())


def canonical(t: dict) -> tuple[str, str]:
    return domain_to_sql_name(t.get("domain_id") or ""), t["table_name"]


def _named_tables(tree: exp.Expr) -> list[exp.Table]:  # pyright: ignore[reportPrivateImportUsage]
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return [
        t for t in tree.find_all(exp.Table) if t.name and not (not t.db and t.name.lower() in ctes)
    ]


def _expand_reads(t: dict, relations: _Relations, seen: set[int]) -> set[str]:
    """The tables a read of ``t`` reads: itself, or a view's own reads."""
    if t["id"] in seen:
        return set()
    seen.add(t["id"])
    view_sql = t.get("view_sql")
    if not view_sql:
        return {".".join(canonical(t))}
    out: set[str] = set()
    for ref in _named_tables(sqlglot.parse_one(view_sql, read="postgres")):
        inner = relations.resolve(ref)
        if inner is not None:
            out |= _expand_reads(inner, relations, seen)
    return out


def _schema(tables: list[dict]) -> dict[str, object]:
    by_domain: dict[str, dict[str, dict[str, str]]] = {}
    for t in tables:
        domain, name = canonical(t)
        by_domain.setdefault(domain, {})[name] = {
            c["column_name"]: _sql_type(c.get("data_type")) for c in t.get("columns") or []
        }
    return dict(by_domain)


def _sql_type(data_type: str | None) -> str:
    """A registered column's type as sqlglot reads it; a type it cannot read is UNKNOWN."""
    if not data_type:
        return "UNKNOWN"
    try:
        exp.DataType.build(data_type, dialect="postgres")
    except (SqlglotError, ValueError):
        return "UNKNOWN"
    return data_type


def derive(name: str, binding: dict, arguments: list[dict], tables: list[dict]) -> Contract:
    """The contract of the statement command ``name`` against ``tables`` (the registered tables,
    each with its ``columns``)."""
    from sqlglot.optimizer.annotate_types import annotate_types
    from sqlglot.optimizer.qualify import qualify

    sql = binding.get("sql") or ""
    digest = statement_hash(sql)
    names = [a["name"] for a in arguments]
    try:
        found = declared(name, binding, names)
    except StatementCommandRefused as exc:
        return Contract(digest, broken=exc.reason)
    relations = _Relations(tables)
    tree = sqlglot.parse_one(found.sql, read="postgres")
    reads: set[str] = set()
    written: dict | None = None
    target = tree.this if isinstance(tree, exp.Insert) else None
    target_table = target.this if isinstance(target, exp.Schema) else target
    for ref in _named_tables(tree):
        t = relations.resolve(ref)
        if t is None:
            said = ".".join(p for p in (ref.catalog, ref.db, ref.name) if p)
            return Contract(
                digest, kind=found.kind, broken=f"no registered table is named {said!r}"
            )
        domain, table = canonical(t)
        ref.set("catalog", None)
        ref.set("db", exp.to_identifier(domain))
        ref.set("this", exp.to_identifier(table))
        if found.writes is not None and (
            ref is target_table or (not isinstance(tree, exp.Insert) and written is None)
        ):
            written = t
            continue
        reads |= _expand_reads(t, relations, set())
    from sqlglot.schema import MappingSchema

    schema = _schema(tables)
    mapping = MappingSchema(schema, dialect="postgres")
    try:
        qualified = qualify(
            tree.copy(), schema=mapping, dialect="postgres", validate_qualify_columns=True
        )
    except OptimizeError as exc:
        return Contract(digest, kind=found.kind, broken=str(exc).split(". Line")[0])
    if written is not None and isinstance(target, exp.Schema):
        have = {c["column_name"] for c in written.get("columns") or []}
        missing = [c.name for c in target.expressions if c.name not in have]
        if missing:
            return Contract(
                digest,
                kind=found.kind,
                broken=f"{'.'.join(canonical(written))} has no column {missing[0]!r}",
            )
    query = qualified.expression if isinstance(qualified, exp.Insert) else qualified
    outputs: tuple[dict[str, str], ...]
    if found.returns_rows and isinstance(query, exp.Query):
        annotated = annotate_types(query, schema=mapping, dialect="postgres")
        outputs = tuple(
            {"name": s.alias_or_name, "type": s.type.sql("postgres") if s.type else "UNKNOWN"}
            for s in annotated.selects
        )
    else:
        outputs = (ROW_COUNT,)
    return Contract(
        statement_hash=digest,
        kind=found.kind,
        writes=".".join(canonical(written)) if written is not None else None,
        upsert=_upserts(tree),
        reads=tuple(sorted(reads)),
        outputs=outputs,
        arguments=_argument_types(qualified, arguments, schema),
        lineage=_lineage(qualified, written),
        write_select=_write_select(tree),
    )


def _write_select(tree: exp.Expr) -> str | None:  # pyright: ignore[reportPrivateImportUsage]
    """The rows a write writes as a SELECT whose columns are the written ones: an INSERT's
    SELECT under the target's column names; an UPDATE's SET expressions over its table."""
    if isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Select):
        select = tree.expression.copy()
        target = tree.this
        if isinstance(target, exp.Schema):
            select.set(
                "expressions",
                [
                    exp.alias_(p.unalias() if isinstance(p, exp.Alias) else p, c.name)
                    for p, c in zip(select.expressions, target.expressions)
                ],
            )
        return select.sql(dialect="postgres")
    if isinstance(tree, exp.Update):
        sets = [e for e in tree.expressions if isinstance(e, exp.EQ)]
        select = exp.select(*[exp.alias_(e.expression.copy(), e.this.name) for e in sets]).from_(
            tree.this.copy()
        )
        where = tree.args.get("where")
        if where is not None:
            select.set("where", where.copy())
        return select.sql(dialect="postgres")
    return None


def _upserts(tree: exp.Expr) -> bool:  # pyright: ignore[reportPrivateImportUsage]
    conflict = tree.args.get("conflict") if isinstance(tree, exp.Insert) else None
    return conflict is not None and bool(conflict.args.get("expressions"))


def _argument_types(
    qualified: exp.Expr,  # pyright: ignore[reportPrivateImportUsage]
    arguments: list[dict],
    schema: dict[str, Any],
) -> tuple[dict[str, str], ...]:
    """Each argument with its type: the type of the column it is compared with, where it is
    compared with one; else its declared type."""
    compared: dict[int, str] = {}
    for p in qualified.find_all(exp.Parameter, exp.Placeholder):
        parent = p.parent
        if isinstance(parent, exp.Binary):
            other = parent.left if parent.right is p else parent.right
            if isinstance(other, exp.Column) and other.table:
                column_type = _column_type(other, qualified, schema)
                if column_type is not None:
                    compared[int(p.name or p.this.this)] = column_type
    return tuple(
        {"name": a["name"], "type": compared.get(i + 1, a.get("type") or "UNKNOWN")}
        for i, a in enumerate(arguments)
    )


def _column_type(column: exp.Column, qualified: exp.Expr, schema: dict) -> str | None:  # pyright: ignore[reportPrivateImportUsage]
    for t in qualified.find_all(exp.Table):
        if t.alias_or_name == column.table:
            return schema.get(t.db, {}).get(t.name, {}).get(column.name)
    return None


def _lineage(qualified: exp.Expr, written: dict | None) -> dict[str, list[str]]:  # pyright: ignore[reportPrivateImportUsage]
    """Each written (or output) column -> the read columns its value is computed from."""
    if isinstance(qualified, exp.Insert):
        select = qualified.expression
        target = qualified.this
        names = (
            [c.name for c in target.expressions]
            if isinstance(target, exp.Schema)
            else [s.alias_or_name for s in select.selects]
        )
    elif isinstance(qualified, exp.Query):
        select = qualified
        names = [s.alias_or_name for s in select.selects]
    else:
        return {}
    if not isinstance(select, exp.Query):
        return {}
    aliases = {t.alias_or_name: f"{t.db}.{t.name}" for t in select.find_all(exp.Table)}
    out: dict[str, list[str]] = {}
    for name, projection in zip(names, select.selects):
        sources = sorted(
            {
                f"{aliases[c.table]}.{c.name}"
                for c in projection.find_all(exp.Column)
                if c.table in aliases
            }
        )
        out[name] = sources
    del written
    return out
