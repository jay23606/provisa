# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The compile preview ("Show SQL") shows the statement the compiled pipeline runs: governed by
the one stage-2 rewrite, so a relationship join on a masked key reads the mask (REQ-740) there too,
and the row filter and the row cap are those the run applies."""

# Requirements: REQ-740, REQ-262

from __future__ import annotations

from types import SimpleNamespace

from provisa.api.admin.dev_queries import _apply_pipeline_transforms
from provisa.compiler.rls import RLSContext
from provisa.compiler.sql_gen import CompilationContext, CompiledQuery, TableMeta
from provisa.compiler.stage2 import apply_governance, build_governance_context
from provisa.security.masking import MaskingRule, MaskType

_ROLE = {"id": "analyst", "capabilities": [], "domain_access": ["*"], "max_rows": 50}
_SQL = (
    'SELECT "t0"."id", "t1"."name" FROM "sales"."orders" "t0" '
    'LEFT JOIN "sales"."customers" "t1" ON "t0"."email" = "t1"."name"'
)


def _meta(table_id: int, name: str) -> TableMeta:
    return TableMeta(
        table_id=table_id,
        field_name=name,
        type_name=name.capitalize(),
        source_id="pg",
        catalog_name="pg",
        schema_name="sales",
        table_name=name,
        domain_id="sales",
    )


def _table(table_id: int, name: str, columns: list[str]) -> dict:
    return {
        "id": table_id,
        "source_id": "pg",
        "domain_id": "sales",
        "schema_name": "sales",
        "table_name": name,
        "columns": [{"column_name": c, "visible_to": []} for c in columns],
    }


def _setting():
    ctx = CompilationContext()
    ctx.tables = {"orders": _meta(1, "orders"), "customers": _meta(2, "customers")}
    rls = RLSContext(rules={1: "region = 'east'"})
    state = SimpleNamespace(
        masking_rules={
            (1, "analyst"): {
                "email": (MaskingRule(mask_type=MaskType.constant, value="***"), "varchar")
            }
        },
        tables=[
            _table(1, "orders", ["id", "email", "region"]),
            _table(2, "customers", ["id", "name"]),
        ],
        relationships=[],
        source_types={"pg": "postgresql"},
        federation_engine=None,
        view_sql_map=None,
        kafka_table_configs=None,
    )
    return ctx, rls, state


def _compiled() -> CompiledQuery:
    return CompiledQuery(sql=_SQL, params=[], root_field="orders", columns=[], sources={"pg"})


def test_the_preview_shows_a_join_on_a_masked_key_reading_the_mask():
    ctx, rls, state = _setting()
    shown, _mv = _apply_pipeline_transforms(_compiled(), ctx, rls, "analyst", _ROLE, [], state)
    assert 'ON \'***\' = "t1"."name"' in shown.sql


def test_the_preview_is_the_statement_the_run_governs():
    ctx, rls, state = _setting()
    shown, _mv = _apply_pipeline_transforms(_compiled(), ctx, rls, "analyst", _ROLE, [], state)
    gov = build_governance_context(
        "analyst", rls, state.masking_rules, ctx, state.tables, role=_ROLE, source_types={}
    )
    assert shown.sql == apply_governance(_SQL, gov)
    assert "region" in shown.sql and "LIMIT 50" in shown.sql
