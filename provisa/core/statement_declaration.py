# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a statement command's statement declares (implementation kind ``statement``, REQ-2001).

The command's binding is ``{"sql": "<one statement>"}``. An argument is written ``{{name}}`` in
the statement, as a MongoDB pipeline command writes one: every placeholder is a declared argument
and every declared argument is used. At registration the placeholders become positional
parameters (``$1`` … in declared order), so a call's values travel as the pipeline's bound
values, never in the statement's text.

The statement is the command's declaration: a SELECT is a query, a write a mutation, and a
write's target is the table the command writes. A declared kind or written table that says
otherwise is refused by name.

A call is run by :mod:`provisa.executor.statement_command`.
"""

# Requirements: REQ-2001

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
import sqlglot.expressions as exp
from sqlglot.errors import SqlglotError

KIND = "statement"
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Merge)


class StatementCommandRefused(ValueError):
    """A statement command that cannot be registered, said naming what is wrong."""

    def __init__(self, command: str, reason: str) -> None:
        self.command = command
        self.reason = reason
        super().__init__(f"command {command!r}: {reason}")


@dataclass(frozen=True)
class Declared:
    """What a statement command's statement declares (REQ-2001)."""

    sql: str  # the statement with its arguments as positional parameters, in declared order
    kind: str  # "query" or "mutation"
    writes: str | None  # the written table as the statement names it, or None for a query
    returns_rows: bool  # a query, or a write with RETURNING; else a write answers its count


def _statement_text(name: str, binding: dict) -> str:
    sql = binding.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise StatementCommandRefused(name, "a statement command's binding holds its SQL as 'sql'")
    return sql


def positional(name: str, sql: str, arguments: list[str]) -> str:
    """``sql`` with each ``{{argument}}`` a positional parameter in declared order: each names a
    declared argument, and each declared argument is used."""
    named = {m.group(1) for m in _PLACEHOLDER.finditer(sql)}
    undeclared = sorted(named - set(arguments))
    if undeclared:
        raise StatementCommandRefused(
            name, f"the statement names {undeclared}, which the command declares as no argument"
        )
    unused = sorted(set(arguments) - named)
    if unused:
        raise StatementCommandRefused(
            name, f"the arguments {unused} appear nowhere in the statement"
        )
    return _PLACEHOLDER.sub(lambda m: f"${arguments.index(m.group(1)) + 1}", sql)


def _parsed(name: str, sql: str, arguments: list[str]) -> exp.Expr:  # pyright: ignore[reportPrivateImportUsage]
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise StatementCommandRefused(name, f"its statement does not parse: {exc}") from exc
    if len(statements) != 1:
        raise StatementCommandRefused(
            name, f"a statement command runs one statement; it holds {len(statements)}"
        )
    tree = statements[0]
    bound = {int(p.this.this) for p in tree.find_all(exp.Parameter) if p.this is not None}
    expected = set(range(1, len(arguments) + 1))
    if bound != expected:
        missing = sorted(arguments[i - 1] for i in expected - bound)
        raise StatementCommandRefused(
            name,
            f"the placeholders of {missing} are inside quotes or a name; an argument is a value",
        )
    return tree


def declared(name: str, binding: dict, arguments: list[str]) -> Declared:
    """What the statement of a command named ``name`` declares."""
    sql = positional(name, _statement_text(name, binding), arguments)
    tree = _parsed(name, sql, arguments)
    if isinstance(tree, _WRITES):
        target = tree.find(exp.Table)
        assert target is not None  # a write names the table it writes
        written = ".".join(p for p in (target.catalog, target.db, target.name) if p)
        return Declared(sql, "mutation", written, tree.args.get("returning") is not None)
    if isinstance(tree, exp.Query):
        return Declared(sql, "query", None, True)
    raise StatementCommandRefused(
        name, f"a {type(tree).__name__} statement is neither a read nor a row write"
    )


def check(name: str, binding: dict, arguments: list[str], kind: str | None, writes: str | None):
    """The command's statement, checked against what is declared beside it: a declared ``kind``
    or written table that contradicts the statement is refused naming both (REQ-2001). Returns
    what the statement declares."""
    found = declared(name, binding, arguments)
    if kind is not None and kind != found.kind:
        raise StatementCommandRefused(
            name, f"it is declared a {kind}, but its statement is a {found.kind}"
        )
    if writes is not None and writes != found.writes:
        raise StatementCommandRefused(
            name,
            f"it is declared as writing {writes!r}, but its statement writes {found.writes!r}"
            if found.writes
            else f"it is declared as writing {writes!r}, but its statement writes nothing",
        )
    return found
