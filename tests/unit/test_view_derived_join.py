# Copyright (c) 2026 Kenneth Stott
# Canary: 7a23fc9a-e99c-4ee0-b682-4f5b07f9a170
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A join along two views' registered relationship relates them, also where a view computes the
joined column -- from an expression, or from a derived table it reads (#270, REQ-603).

``view_dq_results.run_id`` is a CONCAT over ``bronze``; ``view_silver.run_id`` comes from a
derived table that aggregates ``view_dq_results``. Neither is a column of a base table, so the
equality between them related nothing and the reader was refused V002 for a cross join. A column
a view computes is a column of the view, as a constant it gives is. A derived table a caller
writes is no view, and gains nothing from this."""

# Requirements: REQ-603

from __future__ import annotations

from provisa.compiler.sql_gen import CompilationContext, JoinMeta, TableMeta
from provisa.compiler.sql_validator import validate_sql
from provisa.compiler.stage2 import GovernanceContext
from provisa.compiler.view_expand import expand_view_refs

_ROLE = {"id": "analyst", "capabilities": [], "domain_access": ["*"]}
_COLUMNS = {
    1: ["sale_id", "batch_id", "run_id"],  # bronze
    2: ["batch_id", "run_id", "outcome"],  # view_dq_results, a view
    3: ["sale_id", "run_id"],  # view_silver, a view
}
_VIEWS = {
    "view_dq_results": (
        "SELECT batch_id, CONCAT('dq-b', CAST(batch_id AS VARCHAR)) AS run_id, "
        "'pass' AS outcome FROM bronze GROUP BY batch_id"
    ),
    "view_silver": (
        "SELECT b.sale_id, p.run_id FROM bronze AS b JOIN ("
        "SELECT batch_id, MIN(run_id) AS run_id FROM view_dq_results GROUP BY batch_id"
        ") AS p ON p.batch_id = b.batch_id"
    ),
}
_READ = "SELECT r.outcome FROM view_silver AS s JOIN view_dq_results AS r ON r.run_id = s.run_id"


def _meta(table_id: int, name: str) -> TableMeta:
    return TableMeta(
        table_id=table_id,
        field_name=name,
        type_name=name.capitalize(),
        source_id="pg",
        catalog_name="pg",
        schema_name="public",
        table_name=name,
        domain_id="quality",
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
    bronze = _meta(1, "bronze")
    dq, silver = _meta(2, "view_dq_results"), _meta(3, "view_silver")
    ctx = CompilationContext()
    ctx.tables = {"bronze": bronze, "view_dq_results": dq, "view_silver": silver}
    ctx.joins = {
        ("Bronze", "dq"): _join(dq, "batch_id", "batch_id"),
        ("Bronze", "same_batch"): _join(bronze, "batch_id", "batch_id"),
    }
    if related:
        ctx.joins[("View_silver", "dq")] = _join(dq, "run_id", "run_id")
    gov = GovernanceContext()
    gov.table_map = {"bronze": 1, "view_dq_results": 2, "view_silver": 3}
    gov.all_columns = {tid: [(c, "varchar") for c in cols] for tid, cols in _COLUMNS.items()}
    validated = expand_view_refs(sql, _VIEWS, mark=True)
    return [v.message for v in validate_sql(validated, ctx, gov, _ROLE, []) if v.code == "V002"]


def test_a_join_along_the_views_relationship_on_columns_they_compute_is_related():
    assert _v002(_READ) == []


def test_it_still_needs_the_views_relationship():
    assert _v002(_READ, related=False)


def test_a_derived_table_a_caller_writes_is_no_view():
    written = (
        "SELECT r.outcome FROM (SELECT b.sale_id, MIN(b.run_id) AS run_id FROM bronze AS b "
        "GROUP BY b.sale_id) AS s JOIN view_dq_results AS r ON r.run_id = s.run_id"
    )
    assert _v002(written)
