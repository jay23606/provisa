# Copyright (c) 2026 Kenneth Stott
# Canary: 9a3e6c17-4b2d-4f80-8e15-d7c2b0a5f934
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An aggregate field carries the name the row type gives its column (REQ-196, REQ-197).

Under the camelCase convention a snake_case column ``slowest_sql_ms`` is ``slowestSqlMs`` on the
row type, and so it is under ``sum``/``avg``/``stddev``/``variance``/``min``/``max`` of the
``<Type>Aggregate`` root and of ``<Type>GroupBy``, in ``having`` and in ``by``; the compiler
resolves each back to the column. Surfaces that name columns physically (gRPC's proto,
JSON:API) select each aggregate field under its physical name as the alias.
"""

# Requirements: REQ-196, REQ-197

from __future__ import annotations

import pytest
from graphql import GraphQLObjectType, parse, validate

from provisa.compiler import naming as _naming
from provisa.compiler.aggregate_gen import build_agg_fields_type, build_having_exp_type
from provisa.compiler.context import build_context
from provisa.compiler.introspect import ColumnMetadata
from provisa.compiler.schema_gen import SchemaInput, generate_schema
from provisa.compiler.sql_gen import compile_query

_META = {
    "page": ColumnMetadata(column_name="page", data_type="varchar(50)", is_nullable=False),
    "slowest_sql_ms": ColumnMetadata(
        column_name="slowest_sql_ms", data_type="double", is_nullable=True
    ),
    "page_ms": ColumnMetadata(column_name="page_ms", data_type="integer", is_nullable=True),
}
_COLUMNS = [{"column_name": c} for c in _META]
_NAMES = {"page": "page", "slowest_sql_ms": "slowestSqlMs", "page_ms": "pageMs"}


@pytest.fixture
def camel():
    _naming.configure(gql="apollo_graphql", sql="snake")
    yield
    _naming.configure(gql="apollo_graphql", sql="snake")


def test_each_aggregate_function_names_a_column_as_the_row_type_does():
    agg = build_agg_fields_type("SlowPages", _COLUMNS, _META, _NAMES)
    for fn in ("sum", "avg", "stddev", "variance", "min", "max"):
        sub = agg.fields[fn].type
        assert isinstance(sub, GraphQLObjectType)
        assert "slowestSqlMs" in sub.fields and "slowest_sql_ms" not in sub.fields, fn
    having = build_having_exp_type("SlowPages", _COLUMNS, _META, _NAMES)
    assert having is not None
    assert set(having.fields["avg"].type.fields) == {"slowestSqlMs", "pageMs"}


def _model():
    tables = [
        {
            "id": 1,
            "source_id": "pg",
            "domain_id": "sales",
            "schema_name": "public",
            "table_name": "slow_pages",
            "enable_aggregates": True,
            "enable_group_by": True,
            "columns": [{"column_name": c, "visible_to": ["admin"]} for c in _META],
            "write_ops": [],
            "write_returns_rows": True,
            "write_refused_forms": [],
        }
    ]
    si = SchemaInput(
        tables=tables,
        relationships=[],
        column_types={1: list(_META.values())},
        naming_rules=[],
        role={"id": "admin", "capabilities": [], "domain_access": ["*"]},
        domains=[{"id": "sales", "description": "Sales"}],
    )
    return generate_schema(si), build_context(si)


def _compile(schema, ctx, query: str):
    document = parse(query)
    assert validate(schema, document) == []
    return compile_query(document, ctx)[0]


def test_the_aggregate_root_reads_the_column_by_its_field_name(camel):
    schema, ctx = _model()
    old = parse("{ slowPagesAggregate { aggregate { avg { slowest_sql_ms } } } }")
    assert validate(schema, old), "the physical name is not a field of the aggregate"
    compiled = _compile(
        schema, ctx, "{ slowPagesAggregate { aggregate { avg { slowestSqlMs } max { pageMs } } } }"
    )
    assert 'AVG("slowest_sql_ms")' in compiled.sql and 'MAX("page_ms")' in compiled.sql
    assert {(c.nested_in, c.field_name) for c in compiled.columns} >= {
        ("aggregate.avg", "slowestSqlMs"),
        ("aggregate.max", "pageMs"),
    }


def test_group_by_having_and_order_by_resolve_the_field_names(camel):
    schema, ctx = _model()
    compiled = _compile(
        schema,
        ctx,
        "{ slowPagesGroupBy(by: [page], having: {avg: {slowestSqlMs: {gt: 100}}},"
        " order_by: [{pageMs: desc}]) { groupKey aggregate { avg { slowestSqlMs } } } }",
    )
    sql = " ".join(compiled.sql.split())
    assert 'AVG("slowest_sql_ms")' in sql
    assert 'HAVING AVG("slowest_sql_ms") >' in sql
    assert 'ORDER BY "page_ms" DESC' in sql
    assert ("aggregate.avg", "slowestSqlMs") in {
        (c.nested_in, c.field_name) for c in compiled.columns
    }


def test_a_group_by_aggregate_field_answers_under_its_alias(camel):
    schema, ctx = _model()
    compiled = _compile(
        schema,
        ctx,
        "{ slowPagesGroupBy(by: [page]) { aggregate { avg { slowest_sql_ms: slowestSqlMs } } } }",
    )
    assert ("aggregate.avg", "slowest_sql_ms") in {
        (c.nested_in, c.field_name) for c in compiled.columns
    }


def test_grpc_selects_each_aggregate_field_under_its_physical_name(camel):
    from provisa.grpc.query_ir import grpc_table_to_aggregate_graphql_text

    schema, ctx = _model()
    text = grpc_table_to_aggregate_graphql_text(ctx, "SlowPages")
    assert text is not None
    assert "avg { slowest_sql_ms: slowestSqlMs page_ms: pageMs }" in text
    # The text validates against the schema, and its results carry the proto's names.
    compiled = _compile(schema, ctx, text)
    assert ("aggregate.avg", "slowest_sql_ms") in {
        (c.nested_in, c.field_name) for c in compiled.columns
    }


def test_jsonapi_selects_each_aggregate_field_under_its_physical_name(camel):
    from provisa.api.jsonapi.generator import _build_agg_selection

    agg = build_agg_fields_type("SlowPages", _COLUMNS, _META, _NAMES)
    selection = _build_agg_selection(
        agg, ["avg"], {"slowestSqlMs": "slowest_sql_ms", "pageMs": "page_ms", "page": "page"}
    )
    assert selection == "avg { slowest_sql_ms: slowestSqlMs page_ms: pageMs }"
