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
  (``federation.runtime_support.arrow_batches_from_rows``; Flight over a direct route);
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
def test_the_row_stream_today(reported, money):
    schema, _batches = arrow_batches_from_rows(_Stream(_ROWS, _DRIVER_TYPES[reported]))
    assert _types(schema) == {
        **_AGREED,
        "i": pa.int64(),  # finding 2: inferred, not the column's 32 bits
        "money": money,  # finding 1
        "ratio": pa.decimal128(38, 3),  # finding 1: sized by the data
    }


@pytest.mark.parametrize("reported", ["postgres", "duckdb", "none"])
def test_the_row_stream_of_a_result_with_no_rows_today(reported):
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
