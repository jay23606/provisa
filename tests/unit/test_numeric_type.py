# Copyright (c) 2026 Kenneth Stott
# Canary: b3f81c26-7a49-4e05-9d1b-52c6e0a94f73
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A numeric column's recorded precision and scale: one stored spelling, one writer, one reader."""

# Requirements: REQ-1961

from __future__ import annotations

import pyarrow as pa
import pytest
from sqlalchemy import Numeric

from provisa.core.ir_types import to_ir, to_sqlalchemy
from provisa.core.numeric_type import (
    NumericSizeInvalid,
    numeric_arrow_type,
    numeric_size,
    numeric_type,
)


def test_the_stored_form_is_one_spelling_and_reads_back():
    assert numeric_type(18, 2) == "numeric(18,2)"
    assert numeric_size(numeric_type(18, 2)) == (18, 2)
    assert numeric_size(numeric_type(5, 0)) == (5, 0)


@pytest.mark.parametrize("bare", ["numeric", "decimal", "NUMERIC", "integer", "varchar(20)", None])
def test_a_type_that_declares_no_size_has_none(bare):
    assert numeric_size(bare) is None


@pytest.mark.parametrize("spelling", ["decimal(10,2)", "DECIMAL(10, 2)", " numeric ( 10 , 2 ) "])
def test_a_declared_size_is_read_whatever_the_spelling_it_was_typed_in(spelling):
    assert numeric_size(spelling) == (10, 2)


@pytest.mark.parametrize("precision, scale", [(0, 0), (-1, 0), (10, 11), (10, -1), (77, 0)])
def test_a_size_no_numeric_column_can_have_is_refused(precision, scale):
    with pytest.raises(NumericSizeInvalid, match="precision is 1 to 76 and scale is 0 to"):
        numeric_type(precision, scale)


def test_a_non_integer_size_is_refused():
    for precision, scale in ((True, 0), ("10", 2), (10.0, 2), (10, None)):
        with pytest.raises(NumericSizeInvalid):
            numeric_type(precision, scale)  # type: ignore[arg-type]


def test_a_declared_numeric_is_exact_and_an_undeclared_one_is_floating_point():
    assert numeric_arrow_type("numeric(18,2)") == pa.decimal128(18, 2)
    assert numeric_arrow_type("numeric(38,10)") == pa.decimal128(38, 10)
    assert numeric_arrow_type("numeric(50,4)") == pa.decimal256(50, 4)
    assert numeric_arrow_type("numeric") == pa.float64()
    assert numeric_arrow_type("decimal") == pa.float64()


def test_the_vocabulary_and_the_store_ddl_read_the_same_declaration():
    assert to_ir(numeric_type(18, 2)) == "numeric"
    sized = to_sqlalchemy(numeric_type(18, 2))
    assert isinstance(sized, Numeric) and (sized.precision, sized.scale) == (18, 2)
    assert to_sqlalchemy("numeric") is Numeric


# --- the engine edge -----------------------------------------------------------------------------

from provisa.core.numeric_type import (  # noqa: E402
    ReportedNumericMalformed,
    numeric_size_of,
    stored_type_of,
)

# How each engine or source prints a decimal column's type → the size it reports. A new engine
# is one row here.
_REPORTED = [
    ("trino", "decimal(10,2)", (10, 2)),
    ("trino", "decimal(38,0)", (38, 0)),
    ("duckdb", "DECIMAL(10,2)", (10, 2)),
    ("duckdb", "DECIMAL(18,3)", (18, 3)),
    ("clickhouse", "Decimal(10, 2)", (10, 2)),
    ("clickhouse", "Decimal32(4)", (9, 4)),
    ("clickhouse", "Decimal64(4)", (18, 4)),
    ("clickhouse", "Decimal128(10)", (38, 10)),
    ("clickhouse", "Decimal256(20)", (76, 20)),
    ("clickhouse", "Nullable(Decimal(10, 2))", (10, 2)),
    ("clickhouse", "LowCardinality(Nullable(Decimal64(2)))", (18, 2)),
    ("postgres", "numeric(10,2)", (10, 2)),
    ("postgres", "numeric(10)", (10, 0)),
    ("sql standard", "DEC(12, 4)", (12, 4)),
    # Reported with no size: an undeclared numeric.
    ("postgres", "numeric", None),
    ("trino", "decimal", None),
    ("duckdb", "DECIMAL", None),
    # Not decimals.
    ("trino", "varchar(20)", None),
    ("trino", "timestamp(6) with time zone", None),
    ("duckdb", "DOUBLE", None),
    ("clickhouse", "DateTime64(3)", None),
    ("clickhouse", "Nullable(String)", None),
    ("trino", "array(decimal(10,2))", None),
    ("trino", "row(a decimal(10,2))", None),
]


@pytest.mark.parametrize("engine, reported, size", _REPORTED)
def test_the_size_an_engine_reports_is_read_from_how_it_prints_the_type(engine, reported, size):
    assert numeric_size_of(reported) == size, engine


@pytest.mark.parametrize(
    "malformed",
    [
        "decimal(10,2,3)",
        "decimal(a,b)",
        "decimal()",
        "decimal(10,20)",
        "decimal(0,0)",
        "Decimal64",
        "Decimal64(4, 2)",
        "Decimal32(12)",
        "numeric(-1,2)",
    ],
)
def test_a_decimal_whose_size_cannot_be_read_is_an_error_not_an_undeclared_numeric(malformed):
    with pytest.raises(ReportedNumericMalformed, match="size cannot be read"):
        numeric_size_of(malformed)


def test_what_is_stored_is_the_one_spelling_whichever_engine_reported_it():
    printed = ["decimal(10,2)", "DECIMAL(10,2)", "Decimal(10, 2)", "numeric(10,2)"]
    assert {stored_type_of(p) for p in printed} == {"numeric(10,2)"}
    assert stored_type_of("Decimal64(4)") == "numeric(18,4)"
    # Anything else is stored as reported.
    assert stored_type_of("varchar(20)") == "varchar(20)"
    assert stored_type_of("numeric") == "numeric"


def test_the_engines_introspection_seam_hands_on_the_stored_spelling():
    """Both introspection methods of the engine runtime — every engine's types reach the model
    through them — store a sized decimal in the one spelling and leave the rest as reported."""
    import types

    from provisa.federation.runtime import EngineRuntime

    reported = {"amount": "DECIMAL(10,2)", "fee": "Decimal64(4)", "n": "numeric", "name": "VARCHAR"}
    runtime = EngineRuntime.__new__(EngineRuntime)
    runtime._state = None
    runtime._backend = types.SimpleNamespace(
        introspect_by_catalog=lambda state, catalog, schema, table: dict(reported),
        introspect_columns=lambda state, source, schema, table: dict(reported),
    )
    expected = {
        "amount": "numeric(10,2)",
        "fee": "numeric(18,4)",
        "n": "numeric",
        "name": "VARCHAR",
    }
    assert runtime.introspect_by_catalog("c", "s", "t") == expected
    assert runtime.introspect_columns(object(), "s", "t") == expected


# --- the one place a column's type is written -----------------------------------------------------


async def _registered_types(control_plane, columns: dict[str, str]) -> dict[str, str]:
    """Register a table with ``columns`` through the table repository, on a real control plane,
    and return each column's stored type."""
    from sqlalchemy import insert

    from provisa.core.models import Column, Table
    from provisa.core.repositories import table as table_repo
    from provisa.core.schema_org import domains, sources, table_columns

    db = control_plane.org()
    async with db.acquire() as conn:
        # The registered table's source and domain are foreign keys.
        await conn.execute_core(insert(sources).values(id="__derived__", type="duckdb"))
        await conn.execute_core(insert(domains).values(id="sales"))
        await table_repo.upsert(
            conn,
            Table(
                source_id="__derived__",
                domain_id="sales",
                schema_name="public",
                table_name="orders",
                columns=[
                    Column(name=name, data_type=declared, visible_to=["analyst"])
                    for name, declared in columns.items()
                ],
                view_sql="SELECT 1 AS id",
            ),
        )
    async with db.acquire() as conn:
        result = await conn.execute_core(
            table_columns.select().with_only_columns(
                table_columns.c.column_name, table_columns.c.data_type
            )
        )
        return {row.column_name: row.data_type for row in result.fetchall()}


@pytest.mark.asyncio
async def test_a_registration_stores_a_numerics_size_in_the_one_spelling(control_plane):
    """Whoever writes the registration and however they spelled it: the table repository is the
    one place a column's type is written."""
    assert await _registered_types(
        control_plane,
        {
            "a": "DECIMAL(10, 2)",
            "b": "numeric(18,4)",
            "c": "decimal(9)",
            "d": "numeric",
            "e": "integer",
            "f": "character varying(40)",
        },
    ) == {
        "a": "numeric(10,2)",
        "b": "numeric(18,4)",
        "c": "numeric(9,0)",
        "d": "numeric",
        "e": "integer",
        "f": "character varying(40)",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "declared", ["numeric(5,9)", "numeric(0,0)", "decimal(77,2)", "numeric(a,b)"]
)
async def test_a_size_no_numeric_can_have_is_refused_naming_the_column(control_plane, declared):
    with pytest.raises(
        ValueError, match=r"column orders\.amount is declared .* precision is 1 to 76"
    ):
        await _registered_types(control_plane, {"amount": declared})


def test_both_table_mutations_answer_an_impossible_size_with_a_code():
    """The registrar is told which column, by a coded refusal — not by a server error."""
    import inspect

    from provisa.api.admin import schema_mutation, schema_mutation_ops
    from provisa.core.repositories.table import NumericSizeRefused

    refused = NumericSizeRefused("orders", "amount", "numeric(5,9)")
    assert isinstance(refused, ValueError)
    assert (refused.table_name, refused.column, refused.declared) == (
        "orders",
        "amount",
        "numeric(5,9)",
    )
    for module in (schema_mutation, schema_mutation_ops):
        source = inspect.getsource(module)
        assert "except table_repo.NumericSizeRefused as _size:" in source
        assert 'code="schema.numeric_size_invalid"' in source
