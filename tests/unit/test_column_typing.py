# Copyright (c) 2026 Kenneth Stott
# Canary: 8a3d5e72-1c9b-4f04-b6e8-5d2f7a90c1b3
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1965: what a source's native type registers as. A native array, struct or map is a JSON
column with three hidden attributes -- array depth, the innermost element's semantic SQL type, and
the source's own spelling -- decided in one place from one parse of the spelling."""

from __future__ import annotations

import pytest

from provisa.core.ir_types import ColumnTyping, column_typing
from provisa.core.native_types import parse_native_type

# (native spelling, source kind, depth, element type). Arrays of one primitive type.
_ARRAYS_OF_A_PRIMITIVE = [
    ("VARCHAR[]", "duckdb", 1, "text"),
    ("INTEGER[][]", "duckdb", 2, "integer"),
    ("INTEGER[3]", "duckdb", 1, "integer"),
    ("BIGINT[][][]", "duckdb", 3, "bigint"),
    ("DECIMAL(18,2)[]", "duckdb", 1, "numeric(18,2)"),
    ("TIMESTAMP WITH TIME ZONE[]", "duckdb", 1, "timestamp"),
    ("text[]", "postgresql", 1, "text"),
    ("character varying(20)[]", "postgresql", 1, "text"),
    ("numeric(18,2)[]", "postgresql", 1, "numeric(18,2)"),
    ("numeric[]", "postgresql", 1, "numeric"),
    ("timestamp with time zone[]", "postgresql", 1, "timestamp"),
    ("_int4", "postgresql", 1, "integer"),
    ("uuid[]", "cockroachdb", 1, "uuid"),
    ("array(varchar)", "trino", 1, "text"),
    ("array(array(integer))", "trino", 2, "integer"),
    ("array(decimal(10,2))", "trino", 1, "numeric(10,2)"),
    ("array(timestamp(3) with time zone)", "trino", 1, "timestamp"),
    ("Array(String)", "clickhouse", 1, "text"),
    ("Array(Nullable(String))", "clickhouse", 1, "text"),
    ("Array(LowCardinality(String))", "clickhouse", 1, "text"),
    ("Array(Array(UInt8))", "clickhouse", 2, "smallint"),
    ("Array(Int8)", "clickhouse", 1, "smallint"),
    ("Array(Decimal(18, 2))", "clickhouse", 1, "numeric(18,2)"),
    ("Array(DateTime64(3))", "clickhouse", 1, "timestamp"),
    ("ARRAY<STRING>", "bigquery", 1, "text"),
    ("ARRAY<INT64>", "bigquery", 1, "bigint"),
    ("ARRAY<NUMERIC(10, 2)>", "bigquery", 1, "numeric(10,2)"),
    ("array<string>", "databricks", 1, "text"),
    ("array<array<int>>", "databricks", 2, "integer"),
    ("array<decimal(10,2)>", "databricks", 1, "numeric(10,2)"),
    ("array<string>", "hiveserver2", 1, "text"),
    ("ARRAY(NUMBER(10,2))", "snowflake", 1, "numeric(10,2)"),
    ("ARRAY(ARRAY(VARCHAR))", "snowflake", 2, "text"),
]

# (native spelling, source kind). Nested, but not an array of one primitive type: plain JSON.
_PLAIN_JSON = [
    ("STRUCT(a INTEGER, b VARCHAR)", "duckdb"),
    ("STRUCT(a INTEGER, b VARCHAR)[]", "duckdb"),
    ("MAP(VARCHAR, INTEGER)", "duckdb"),
    ("UNION(num INTEGER, str VARCHAR)[]", "duckdb"),
    ("row(a integer, b array(varchar))", "trino"),
    ("array(row(a integer, b varchar))", "trino"),
    ("map(varchar, integer)", "trino"),
    ("Tuple(String, UInt8)", "clickhouse"),
    ("Map(String, UInt8)", "clickhouse"),
    ("Nested(a String, b UInt8)", "clickhouse"),
    ("Array(Tuple(String, UInt8))", "clickhouse"),
    ("Array(IPv4)", "clickhouse"),  # an element with no semantic SQL type
    ("STRUCT<a INT64, b ARRAY<STRING>>", "bigquery"),
    ("ARRAY<STRUCT<a INT64>>", "bigquery"),
    ("struct<a:int,b:string>", "databricks"),
    ("map<string,int>", "databricks"),
    ("array<struct<a:int>>", "hiveserver2"),
    ("ARRAY", "snowflake"),  # each element a VARIANT
    ("OBJECT", "snowflake"),
    ("VARIANT", "snowflake"),
    ("OBJECT(a NUMBER, b VARCHAR)", "snowflake"),
    ("ARRAY", "postgresql"),  # information_schema's marker: an array, element not stated
]

# (native spelling, source kind). Not natively nested: the listed spelling, none of the three.
_NOT_NESTED = [
    ("jsonb", "postgresql"),
    ("super", "redshift"),  # holds any JSON value: JSON at its source
    ("json", "mysql"),
    ("numeric(18,2)", "postgresql"),
    ("timestamp(3) with time zone", "trino"),
    ("varchar(20)", "mysql"),
    ("character varying", "postgresql"),
    ("Nullable(String)", "clickhouse"),
    ("geography", "snowflake"),
]


@pytest.mark.parametrize(("native", "platform", "depth", "element"), _ARRAYS_OF_A_PRIMITIVE)
def test_an_array_of_a_primitive_is_json_with_its_depth_and_element_type(
    native, platform, depth, element
):
    assert column_typing(native, platform) == ColumnTyping(
        data_type="json",
        array_depth=depth,
        element_type=element,
        native_type=native.strip().lower(),
    )


@pytest.mark.parametrize(("native", "platform"), _PLAIN_JSON)
def test_a_struct_a_map_or_an_array_of_them_is_plain_json_with_its_native_type(native, platform):
    assert column_typing(native, platform) == ColumnTyping(
        data_type="json", array_depth=0, element_type=None, native_type=native.strip().lower()
    )


@pytest.mark.parametrize(("native", "platform"), _NOT_NESTED)
def test_a_column_that_is_not_natively_nested_carries_none_of_the_three(native, platform):
    typing = column_typing(native, platform)
    assert (typing.array_depth, typing.element_type, typing.native_type) == (0, None, None)
    assert typing.data_type == native.strip().lower()


@pytest.mark.parametrize("platform", ["postgresql", "greenplum", "yugabytedb", "cockroachdb"])
def test_a_postgres_family_array_has_depth_one_however_it_is_spelled(platform):
    """PostgreSQL's array type records no dimensions; a declared ``integer[][]`` is an
    ``integer[]``. CockroachDB cannot nest arrays."""
    assert column_typing("integer[][]", platform).array_depth == 1


def test_bigquery_cannot_nest_an_array():
    assert column_typing("ARRAY<INT64>", "bigquery").array_depth == 1


def test_the_parse_keeps_the_structure_and_never_names_a_model_type():
    shape = parse_native_type("array(map(varchar, array(row(a integer, b varchar))))")
    assert shape.kind == "array"
    assert shape.element is not None and shape.element.kind == "map"
    value = shape.element.element
    assert value is not None and value.kind == "array"
    assert value.element is not None and value.element.kind == "struct"
    assert value.element.fields == ("a integer", "b varchar")
    assert parse_native_type("timestamp(3) with time zone").kind == "scalar"
    assert parse_native_type("varchar(3)").kind == "scalar"
    assert parse_native_type("arraylike").kind == "scalar"
