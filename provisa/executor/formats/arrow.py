# Copyright (c) 2026 Kenneth Stott
# Canary: 13fbb4d0-69b5-46e2-af68-f3bbda539ef7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Arrow IPC buffer serialization (REQ-051)."""

from __future__ import annotations

import io
from decimal import Decimal

import pyarrow as pa

from provisa.compiler.sql_gen import ColumnRef

# Requirements: REQ-045, REQ-051


def _column_names(columns: list[ColumnRef]) -> list[str]:
    return [
        f"{col.nested_in}.{col.field_name}" if col.nested_in else col.field_name for col in columns
    ]


def _convert(val):
    if isinstance(val, Decimal):
        return float(val)
    return val


def rows_to_arrow_ipc(  # REQ-051
    rows: list[tuple],
    columns: list[ColumnRef],
) -> bytes:
    """Serialize rows to Arrow IPC format (stream)."""
    names = _column_names(columns)
    col_data: dict[str, list] = {name: [] for name in names}
    for row in rows:
        for i, name in enumerate(names):
            col_data[name].append(_convert(row[i]))

    table = pa.table(col_data)
    buf = io.BytesIO()
    writer = pa.ipc.new_stream(buf, table.schema)
    writer.write_table(table)
    writer.close()
    return buf.getvalue()


def rows_to_arrow_table(  # REQ-045, REQ-051
    rows: list[tuple],
    columns: list[ColumnRef],
    *,
    shape: list[tuple[str, str]] | None = None,
    result_names: list[str] | None = None,
    result_types: list[str] | None = None,
) -> pa.Table:
    """Convert rows to a PyArrow Table (for Arrow Flight).

    ``shape`` is the governed statement's result columns and their registered types (the plan's
    ``result_shape``, REQ-1961), named as the statement's result names them — ``result_names``,
    parallel to ``columns``, when those differ from the names the table is given. A result
    column that is a registered column is read as its registered type, with or without rows
    (``runtime_support.read_targets`` / ``typed_arrow_array``, the row stream's own rule);
    every other column is typed as the row stream types it (``arrow_array_for_rows``): from
    ``result_types``, the driver's own column types, where it reports a decimal's size, and
    from its values otherwise — a decimal with no size is floating point.
    """
    from provisa.federation.runtime_support import (
        arrow_array_for_rows,
        read_targets,
        typed_arrow_array,
    )

    names = _column_names(columns)
    targets = read_targets(result_names if result_names is not None else names, shape)
    arrays = []
    for i, name in enumerate(names):
        values = [row[i] for row in rows]
        if targets[i] is not None:
            arrays.append(typed_arrow_array(values, targets[i], name))
        else:
            arrays.append(arrow_array_for_rows(values, result_types[i] if result_types else None))
    return pa.table(arrays, names=names)
