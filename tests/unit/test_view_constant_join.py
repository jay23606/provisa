# Copyright (c) 2026 Kenneth Stott
# Canary: 70567724-20b4-4514-8eb2-59bd1efefb46
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A join on a view's column relates the tables along the view's registered relationship, also
where the view's SQL gives that column as a constant (REQ-603).

The view ``evokes`` gives each line it reads with the theme it evokes, as a constant
(``'time' AS theme_id``); ``evokes.theme_id = theme.id`` is registered. The statement governance
validates has every view expanded, so before this the constant left ``theme`` joined to nothing
and the reader was refused V002 for a cross join. A derived table a caller writes is no view, and
gains nothing from this."""

# Requirements: REQ-603

from __future__ import annotations

from provisa.compiler.sql_gen import CompilationContext, JoinMeta, TableMeta
from provisa.compiler.sql_validator import validate_sql
from provisa.compiler.stage2 import GovernanceContext
from provisa.compiler.view_expand import VIEW_MARK, expand_view_refs

_ROLE = {"id": "analyst", "capabilities": [], "domain_access": ["*"]}
_COLUMNS = {
    1: ["id", "text"],  # line
    2: ["id", "name"],  # theme
    3: ["line_id", "theme_id"],  # evokes, a view
}
_EVOKES = "SELECT l.id AS line_id, 'time' AS theme_id FROM line l"
_READ = "SELECT t.name, e.line_id FROM evokes e JOIN theme t ON t.id = e.theme_id"


def _meta(table_id: int, name: str) -> TableMeta:
    return TableMeta(
        table_id=table_id,
        field_name=name,
        type_name=name.capitalize(),
        source_id="pg",
        catalog_name="pg",
        schema_name="public",
        table_name=name,
        domain_id="sonnets",
        source_type="postgresql",
    )


def _join(target: TableMeta, source_column: str, target_column: str) -> JoinMeta:
    return JoinMeta(
        source_column=source_column,
        target_column=target_column,
        source_column_type="varchar",
        target_column_type="varchar",
        target=target,
        cardinality="many-to-one",
    )


def _v002(sql: str, *, related: bool = True) -> list[str]:
    """V002 for ``sql``, its views expanded as governance validates them. ``related``: whether
    ``evokes.theme_id = theme.id`` and ``evokes.line_id = line.id`` are registered."""
    line, theme, evokes = _meta(1, "line"), _meta(2, "theme"), _meta(3, "evokes")
    ctx = CompilationContext()
    ctx.tables = {"line": line, "theme": theme, "evokes": evokes}
    if related:
        ctx.joins = {
            ("Evokes", "theme"): _join(theme, "theme_id", "id"),
            ("Evokes", "line"): _join(line, "line_id", "id"),
        }
    gov = GovernanceContext()
    gov.table_map = {"line": 1, "theme": 2, "evokes": 3}
    gov.all_columns = {tid: [(c, "varchar") for c in cols] for tid, cols in _COLUMNS.items()}
    validated = expand_view_refs(sql, {"evokes": _EVOKES}, mark=True)
    return [v.message for v in validate_sql(validated, ctx, gov, _ROLE, []) if v.code == "V002"]


def test_a_join_on_a_constant_a_view_gives_relates_along_the_view_s_relationship():
    assert _v002(_READ) == []


def test_it_still_needs_the_view_s_relationship():
    assert _v002(_READ, related=False) == [
        "Invalid JOIN: theme.id = evokes.theme_id — no approved relationship exists between "
        "these tables on these columns"
    ]


def test_a_derived_table_a_caller_writes_is_no_view():
    written = (
        "SELECT t.name FROM (SELECT l.id AS line_id, 'time' AS theme_id FROM line l) e "
        "JOIN theme t ON t.id = e.theme_id"
    )
    assert any("no condition relating them" in m for m in _v002(written))


def test_a_mark_the_process_did_not_make_is_no_view():
    forged = (
        "SELECT t.name FROM (SELECT * FROM (SELECT l.id AS line_id, 'time' AS theme_id "
        'FROM line l) AS "__view_0000000000000000__evokes") e JOIN theme t ON t.id = e.theme_id'
    )
    assert not forged.count(VIEW_MARK)
    assert any("no condition relating them" in m for m in _v002(forged))


def test_a_cross_join_inside_the_view_is_still_refused():
    inside = "SELECT l.id AS line_id, 'time' AS theme_id FROM line l, theme t2"
    line, theme, evokes = _meta(1, "line"), _meta(2, "theme"), _meta(3, "evokes")
    ctx = CompilationContext()
    ctx.tables = {"line": line, "theme": theme, "evokes": evokes}
    ctx.joins = {("Evokes", "theme"): _join(theme, "theme_id", "id")}
    gov = GovernanceContext()
    gov.table_map = {"line": 1, "theme": 2, "evokes": 3}
    gov.all_columns = {tid: [(c, "varchar") for c in cols] for tid, cols in _COLUMNS.items()}
    validated = expand_view_refs(_READ, {"evokes": inside}, mark=True)
    messages = [v.message for v in validate_sql(validated, ctx, gov, _ROLE, []) if v.code == "V002"]
    assert any("line and theme are combined with no condition" in m for m in messages), messages
