# Copyright (c) 2026 Kenneth Stott
# Canary: b56f4ab6-ab27-4042-b53b-8728140b9315
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A compiled aggregate is routed to a view that pre-aggregates its table (REQ-198, REQ-882).

The compiled statement names its table by schema and table; the role's context says which
registered table that is, and its catalog, so the view over that catalog's table answers it.
A role that reads the table through a row filter or a mask is never answered from the view,
which was computed over every row.
"""

# Requirements: REQ-198, REQ-882

from __future__ import annotations

from types import SimpleNamespace

from provisa.compiler.sql_gen import CompiledQuery
from provisa.compiler.sql_types import CompilationContext, TableMeta
from provisa.mv.models import MVDefinition, MVStatus
from provisa.mv.rewriter import rewrite_if_mv_match, role_governed_tables

_VIEW_SQL = (
    'SELECT "region", COUNT(*) AS "n", SUM("amount") AS "total" '
    'FROM "sales_pg"."public"."orders" GROUP BY "region"'
)
_QUERY = 'SELECT "region", SUM("amount") FROM "public"."orders" GROUP BY "region"'


def _ctx() -> CompilationContext:
    ctx = CompilationContext()
    ctx.tables["orders"] = TableMeta(
        table_id=7,
        field_name="orders",
        type_name="Orders",
        source_id="sales-pg",
        catalog_name="sales_pg",
        schema_name="public",
        table_name="orders",
        domain_id="sales",
    )
    return ctx


def _compiled(sql: str = _QUERY) -> CompiledQuery:
    return CompiledQuery(sql=sql, params=[], root_field="orders", columns=[], sources={"sales-pg"})


def _rollup() -> MVDefinition:
    return MVDefinition(
        id="orders_by_region",
        source_tables=["orders"],
        target_catalog="mat",
        target_schema="mv",
        target_table="orders_by_region",
        sql=_VIEW_SQL,
        status=MVStatus.FRESH,
    )


def test_a_compiled_aggregate_is_read_from_the_view_over_its_table():
    routed = rewrite_if_mv_match(_compiled(), [_rollup()], _ctx(), frozenset())
    assert routed.sources == {"mat"}
    assert '"mat"."mv"."orders_by_region"' in routed.sql
    assert 'SUM("total")' in routed.sql


def test_a_role_with_a_row_filter_or_a_mask_on_the_table_reads_the_table():
    compiled = _compiled()
    assert rewrite_if_mv_match(compiled, [_rollup()], _ctx(), frozenset({7})) is compiled


def test_a_view_over_another_catalogs_table_of_the_same_name_does_not_answer():
    other = _rollup()
    other.sql = _VIEW_SQL.replace('"sales_pg"', '"crm_pg"')
    compiled = _compiled()
    assert rewrite_if_mv_match(compiled, [other], _ctx(), frozenset()) is compiled


def test_the_governed_tables_are_those_a_role_reads_filtered_or_masked():
    ctx = _ctx()
    ctx.tables["lines"] = TableMeta(
        table_id=8,
        field_name="lines",
        type_name="Lines",
        source_id="sales-pg",
        catalog_name="sales_pg",
        schema_name="public",
        table_name="lines",
        domain_id="ops",
    )
    rls = SimpleNamespace(rules={}, domain_rules={})
    assert role_governed_tables(ctx, rls, {}, "analyst") == frozenset()
    assert role_governed_tables(
        ctx, SimpleNamespace(rules={7: "region = 'us'"}, domain_rules={}), {}, "analyst"
    ) == frozenset({7})
    assert role_governed_tables(
        ctx, SimpleNamespace(rules={}, domain_rules={"ops": "true"}), {}, "analyst"
    ) == frozenset({8})
    masks = {(7, "analyst"): {"amount": ("mask", "integer")}, (8, "other"): {"x": ("m", "t")}}
    assert role_governed_tables(ctx, rls, masks, "analyst") == frozenset({7})
