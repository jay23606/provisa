# Copyright (c) 2026 Kenneth Stott
# Canary: a7c2e915-4d38-4b06-9f1e-63b0d8a52c47
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The Arrow type each read path gives each kind of column (REQ-1961).

A governed read reaches a client as Arrow by one of four paths, and each typed its columns its
own way. This file states, column kind by column kind, what each path answers — captured from
the code as it stood before the paths were brought to one rule, so that every change to a path
shows here as a changed expectation and nothing changes unseen.

The four paths:

- **row stream** — a source read as rows and packed into Arrow as it streams
  (``federation.runtime_support.arrow_batches_from_rows``; Flight over a direct route). ON THE
  ONE RULE since REQ-1961: given the governed statement's result shape, each column is read as
  its registered type; the "today" cases below are what it does without a shape;
- **materialised** — a whole row result turned into a table
  (``executor.formats.arrow.rows_to_arrow_table``; Flight's buffered answers);
- **engine stream** — the engine's own Arrow reader, passed through (its types are the
  engine's; nothing here types it, so it has no row in these tables);
- **Airport** — a direct scan typed from the driver's column types
  (``api.airport.query._direct_typed_schema``).

Where the paths DISAGREE today (the findings; the one rule's answer is the registered type):

1. A numeric column: the row stream gives ``decimal128(p, s)`` only when the result's own
   column type carries the size, else ``decimal128(38, s)`` with ``s`` read off the first
   batch's values; the materialised path and Airport give ``double``, declared or not.
2. A 32-bit integer column: the row stream and the materialised path give ``int64`` (inferred
   from Python ints); Airport gives ``int32`` (from the driver's type).
3. A result with no rows: the row stream and the materialised path give every column the
   ``null`` type; Airport gives the same types as a result with rows.
"""

# Requirements: REQ-1961

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pyarrow as pa
import pytest

from provisa.api.airport.query import _direct_typed_schema
from provisa.compiler.result_shape import RegisteredType
from provisa.compiler.sql_gen import ColumnRef
from provisa.executor.formats.arrow import rows_to_arrow_table
from provisa.federation.runtime_support import arrow_batches_from_rows

# One result, a column of every kind: its name, the type name a Postgres driver reports for it
# and the one DuckDB reports, and two values.
_COLUMNS = [
    ("i", "int4", "INTEGER", [1, 2]),
    ("b", "int8", "BIGINT", [10**12, None]),
    ("money", "numeric", "DECIMAL(18,2)", [Decimal("12.50"), Decimal("0.10")]),
    ("ratio", "numeric", "DECIMAL", [Decimal("0.125"), Decimal("3")]),
    ("f", "float8", "DOUBLE", [1.5, 2.5]),
    ("t", "text", "VARCHAR", ["a", "b"]),
    ("ts", "timestamp", "TIMESTAMP", [dt.datetime(2026, 1, 2, 3, 4, 5), None]),
    ("d", "date", "DATE", [dt.date(2026, 1, 2), dt.date(2026, 1, 3)]),
    ("ok", "bool", "BOOLEAN", [True, False]),
]
_NAMES = [c[0] for c in _COLUMNS]
_ROWS = [tuple(c[3][r] for c in _COLUMNS) for r in range(2)]
_DRIVER_TYPES = {
    "postgres": [c[1] for c in _COLUMNS],
    "duckdb": [c[2] for c in _COLUMNS],
    "none": None,
}

# The columns every path agrees on, whatever reported their types.
_AGREED = {
    "b": pa.int64(),
    "f": pa.float64(),
    "t": pa.string(),
    "ts": pa.timestamp("us"),
    "d": pa.date32(),
    "ok": pa.bool_(),
}
_NULLS = dict.fromkeys(_NAMES, pa.null())


class _Stream:
    """A lazy row result, as a direct-route driver hands one over."""

    def __init__(self, rows: list[tuple], types: list[str] | None) -> None:
        self._rows = rows
        self.column_names = _NAMES
        self.column_types = types

    def iter_rows(self):
        return iter(self._rows)


def _types(schema: pa.Schema) -> dict[str, pa.DataType]:
    return {field.name: field.type for field in schema}


# --- the row stream --------------------------------------------------------------------------------

# The same result's columns as the model registers them: what the governed statement's result
# shape (compiler.result_shape) says each one is.
_REGISTERED = [
    (name, RegisteredType(declared))
    for name, declared in [
        ("i", "integer"),
        ("b", "bigint"),
        ("money", "numeric(18,2)"),
        ("ratio", "numeric"),
        ("f", "double"),
        ("t", "varchar"),
        ("ts", "timestamp"),
        ("d", "date"),
        ("ok", "boolean"),
    ]
]
# The one rule (REQ-1961): the registered type, on every path. An integer is 32 bits; a numeric
# is exact where the model records its size and floating point where it does not.
_BY_THE_RULE = {
    **_AGREED,
    "i": pa.int32(),
    "money": pa.decimal128(18, 2),
    "ratio": pa.float64(),
}


@pytest.mark.parametrize("reported", ["postgres", "duckdb", "none"])
@pytest.mark.parametrize("rows", [_ROWS, []], ids=["rows", "no rows"])
def test_the_row_stream_reads_each_column_as_its_registered_type(reported, rows):
    """Whatever the driver reported, whatever the first rows held, and with no rows at all."""
    schema, batches = arrow_batches_from_rows(
        _Stream(rows, _DRIVER_TYPES[reported]), shape=_REGISTERED
    )
    assert _types(schema) == _BY_THE_RULE
    for batch in batches:
        assert batch.schema == schema


def test_an_undeclared_numeric_is_floating_point_and_says_what_that_costs():
    """0.1 + 0.2 as decimals is exactly 0.3. Read as floating point it is approximately 0.3 —
    here the double Arrow's column-wise cast produces, which is not even the double nearest
    0.3. Declare the column's precision and scale for exact values."""
    rows = [(Decimal("0.1") + Decimal("0.2"),)]
    exact = Decimal("0.3")

    class _One(_Stream):
        def __init__(self) -> None:
            self._rows, self.column_names, self.column_types = rows, ["v"], ["numeric"]

    schema, batches = arrow_batches_from_rows(_One(), shape=[("v", RegisteredType("numeric"))])
    (value,) = next(batches).column(0).to_pylist()
    assert schema.field("v").type == pa.float64()
    assert isinstance(value, float) and value == pytest.approx(0.3, abs=1e-15)
    assert Decimal(value) != exact, "a double cannot hold 0.3"
    schema, batches = arrow_batches_from_rows(
        _One(), shape=[("v", RegisteredType("numeric(10,1)"))]
    )
    assert schema.field("v").type == pa.decimal128(10, 1)
    assert next(batches).column(0).to_pylist() == [exact]


def test_values_that_cannot_be_read_as_the_registered_type_are_an_error_naming_the_column():
    """Three digits after the point in a column registered with two: never rounded silently."""
    from provisa.federation.runtime_support import ColumnTypeMismatch

    rows = [tuple(Decimal("12.505") if n == "money" else v for n, v in zip(_NAMES, _ROWS[0]))]
    with pytest.raises(ColumnTypeMismatch, match="column 'money'"):
        schema, batches = arrow_batches_from_rows(_Stream(rows, None), shape=_REGISTERED)
        list(batches)


def test_a_column_the_shape_does_not_type_keeps_the_type_its_values_give_it():
    """No registered type by that name, a type neither vocabulary names, or JSON (REQ-1965: a
    JSON column's read form is its reader's): read off the values, as without a shape."""
    shape = [
        ("i", RegisteredType("USER-DEFINED")),
        ("t", RegisteredType("json")),
        ("ok", RegisteredType("boolean")),
    ]  # "b" is not in it
    schema, _batches = arrow_batches_from_rows(_Stream(_ROWS, None), shape=shape)
    types = _types(schema)
    assert types["i"] == pa.int64() and types["b"] == pa.int64() and types["t"] == pa.string()
    assert types["ok"] == pa.bool_()


def test_a_computed_column_keeps_the_type_its_engine_gives_it():
    """The model declares columns, not expressions. ``amount * amount`` over numeric(18,2) is
    four digits after the point on the engine; SQLGlot annotates it ``DECIMAL(18, 2)``. Typing
    it by that annotation would refuse a correct answer, so a computed column is not typed by
    the shape: its values, exact as the engine sent them, decide."""
    rows = [(Decimal("156.2500"), Decimal("12.50"))]

    class _Two(_Stream):
        def __init__(self) -> None:
            self._rows, self.column_names, self.column_types = rows, ["sq", "amount"], None

    shape = [("sq", "DECIMAL(18, 2)"), ("amount", RegisteredType("numeric(18,2)"))]
    schema, batches = arrow_batches_from_rows(_Two(), shape=shape)
    assert schema.field("sq").type == pa.decimal128(38, 4)
    assert schema.field("amount").type == pa.decimal128(18, 2)
    assert next(batches).column(0).to_pylist() == [Decimal("156.2500")]


def test_the_shape_marks_which_result_columns_are_registered_columns():
    from tests.unit.test_result_shape import _shape

    shape = dict(
        _shape(
            "SELECT o.order_id, o.amount AS total, o.amount * o.amount AS sq, "
            "sum(o.amount) OVER () AS running FROM sales.orders o"
        )
    )
    assert isinstance(shape["order_id"], RegisteredType)
    assert isinstance(shape["total"], RegisteredType) and shape["total"] == "numeric(18,2)"
    assert not isinstance(shape["sq"], RegisteredType)
    assert not isinstance(shape["running"], RegisteredType)
    (star,) = [_shape("SELECT * FROM sales.orders")]
    assert all(isinstance(declared, RegisteredType) for _name, declared in star)


@pytest.mark.parametrize(
    "reported, money",
    [
        # The size comes from the RESULT's column type, when it carries one...
        ("duckdb", pa.decimal128(18, 2)),
        # ...and otherwise from the widest scale among the first batch's values.
        ("postgres", pa.decimal128(38, 2)),
        ("none", pa.decimal128(38, 2)),
    ],
)
def test_the_row_stream_without_a_shape(reported, money):
    """A read that is not a governed plan's (the engine seam's own row adapter) has no shape."""
    schema, _batches = arrow_batches_from_rows(_Stream(_ROWS, _DRIVER_TYPES[reported]))
    assert _types(schema) == {
        **_AGREED,
        "i": pa.int64(),  # finding 2: inferred, not the column's 32 bits
        "money": money,  # finding 1
        "ratio": pa.decimal128(38, 3),  # finding 1: sized by the data
    }


@pytest.mark.parametrize("reported", ["postgres", "duckdb", "none"])
def test_the_row_stream_of_a_result_with_no_rows_without_a_shape(reported):
    schema, _batches = arrow_batches_from_rows(_Stream([], _DRIVER_TYPES[reported]))
    assert _types(schema) == _NULLS  # finding 3


# --- the materialised table ------------------------------------------------------------------------


def _column_refs() -> list[ColumnRef]:
    return [ColumnRef(alias=None, column=n, field_name=n, nested_in=None) for n in _NAMES]


def test_the_materialised_table_today():
    assert _types(rows_to_arrow_table(_ROWS, _column_refs()).schema) == {
        **_AGREED,
        "i": pa.int64(),  # finding 2
        "money": pa.float64(),  # finding 1: every Decimal becomes a float
        "ratio": pa.float64(),
    }


def test_the_materialised_table_of_a_result_with_no_rows_today():
    assert _types(rows_to_arrow_table([], _column_refs()).schema) == _NULLS  # finding 3


# --- Airport ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("reported", ["postgres", "duckdb"])
def test_airport_today(reported):
    """Typed from the driver's column types alone, so the same with or without rows."""
    assert _types(_direct_typed_schema(_NAMES, _DRIVER_TYPES[reported])) == {
        **_AGREED,
        "i": pa.int32(),
        "money": pa.float64(),  # finding 1: its numeric is a float, sized or not
        "ratio": pa.float64(),
    }


def test_airport_refuses_a_scan_whose_driver_reports_no_types():
    with pytest.raises(ValueError, match="cannot form a byte-stable schema"):
        _direct_typed_schema(_NAMES, None)


# --- what the paths agree on -----------------------------------------------------------------------


def test_the_columns_every_path_types_alike():
    """bigint, double, text, timestamp, date and boolean: one answer on all three paths that
    type a result, which is what the one rule must keep."""
    row_stream, _ = arrow_batches_from_rows(_Stream(_ROWS, _DRIVER_TYPES["postgres"]))
    materialised = rows_to_arrow_table(_ROWS, _column_refs()).schema
    airport = _direct_typed_schema(_NAMES, _DRIVER_TYPES["postgres"])
    for name, arrow_type in _AGREED.items():
        answers = {
            row_stream.field(name).type,
            materialised.field(name).type,
            airport.field(name).type,
        }
        assert answers == {arrow_type}, name


# --- the one rule ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "registered, arrow_type",
    [
        ("integer", pa.int32()),
        ("int4", pa.int32()),
        ("smallint", pa.int16()),
        ("bigint", pa.int64()),
        ("real", pa.float32()),
        ("double precision", pa.float64()),
        ("numeric(18,2)", pa.decimal128(18, 2)),
        ("decimal(10,2)", pa.decimal128(10, 2)),
        ("numeric(50,4)", pa.decimal256(50, 4)),
        ("numeric", pa.float64()),
        ("decimal", pa.float64()),
        ("character varying(40)", pa.string()),
        ("timestamp without time zone", pa.timestamp("us")),
        ("boolean", pa.bool_()),
        ("json", pa.string()),
        ("array(varchar)", pa.string()),  # REQ-1965: nested is JSON
    ],
)
def test_the_arrow_type_of_a_registered_type(registered, arrow_type):
    from provisa.core.catalog_types import column_arrow_type

    assert column_arrow_type(registered) == arrow_type


@pytest.mark.parametrize("registered", [None, "", "USER-DEFINED", "geometry"])
def test_a_type_neither_vocabulary_names_has_no_arrow_type_of_its_own(registered):
    from provisa.core.catalog_types import column_arrow_type

    assert column_arrow_type(registered) is None


def test_flights_direct_stream_is_typed_by_the_plans_result_shape():
    """The call site: the governed statement's result shape, kept with the statement, is what
    the row adapter is handed."""
    import inspect

    from provisa.api.flight import server

    source = inspect.getsource(server)
    assert "self._run_on_loop(plan.result_shape())" in source
    assert "arrow_batches_from_rows(stream, shape=shape)" in source
