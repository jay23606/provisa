# Copyright (c) 2026 Kenneth Stott
# Canary: af6397d8-a84c-47ac-95b2-48c915eeb74f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A pipeline table's rows, checked against its output columns on the way out (REQ-1980).

The output columns are fixed at registration. Each document the pipeline returns is projected
onto them -- a column reads its ``path`` (dot notation) where it has one, else its name. A field
the document lacks is null; a field of another type than its column's fails the read, naming the
table, the column and the type found: no row is ever served part-checked. Fields no column reads
are left out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

_INTEGERS = frozenset({"smallint", "integer", "int", "bigint", "int2", "int4", "int8"})
_FLOATS = frozenset({"float", "double", "real", "float4", "float8"})


@dataclass(frozen=True)
class OutputColumn:
    name: str
    data_type: str
    path: str | None = None


class PipelineOutputMismatch(ValueError):
    """A document whose field is not of its column's type."""

    def __init__(self, table: str, column: str, data_type: str, found: str) -> None:
        self.params = {"table": table, "column": column, "type": data_type, "found": found}
        super().__init__(
            f"Table {table!r}: the pipeline returned a {found} for column {column!r}, which is "
            f"{data_type}"
        )


def _read(doc: dict, path: str) -> Any:
    node: Any = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _type_name(value: Any) -> str:
    return type(value).__name__


def _cell(value: Any, data_type: str, dates_as_text: bool = False) -> Any:
    """``value`` as its column's type, or ValueError. With ``dates_as_text`` a date or timestamp
    column reads an ISO 8601 string, as a source with no date type holds one (Cosmos DB)."""
    from bson import Binary, Decimal128, ObjectId, json_util

    base = data_type.strip().lower().split("(")[0].strip()
    if base in _INTEGERS:
        if isinstance(value, int) and not isinstance(value, bool):
            return int(value)
        raise ValueError
    if base in _FLOATS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError
    if base in ("numeric", "decimal"):
        if isinstance(value, Decimal128):
            return value.to_decimal()
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return Decimal(str(value))
        raise ValueError
    if base in ("boolean", "bool"):
        if isinstance(value, bool):
            return value
        raise ValueError
    if dates_as_text and isinstance(value, str) and base in ("timestamp", "timestamptz", "date"):
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if base == "date":
            return moment.date()
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    if base in ("timestamp", "timestamptz", "datetime"):
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        raise ValueError
    if base == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raise ValueError
    if base == "uuid":
        if isinstance(value, Binary) and value.subtype in (3, 4):
            return value.as_uuid(value.subtype)
        raise ValueError
    if base in ("json", "jsonb"):
        # Any document or array, written as relaxed Extended JSON text.
        return json.loads(json_util.dumps(value, json_options=json_util.RELAXED_JSON_OPTIONS))
    if base in ("text", "varchar", "char", "string"):
        if isinstance(value, str):
            return value
        if isinstance(value, ObjectId):
            return str(value)
        raise ValueError
    raise ValueError


def project(
    table: str, doc: dict, columns: list[OutputColumn], *, dates_as_text: bool = False
) -> dict:
    """One returned document as the table's row."""
    row: dict[str, Any] = {}
    for col in columns:
        value = _read(doc, col.path or col.name)
        if value is None:
            row[col.name] = None
            continue
        try:
            row[col.name] = _cell(value, col.data_type, dates_as_text)
        except ValueError:
            raise PipelineOutputMismatch(
                table, col.name, col.data_type, _type_name(value)
            ) from None
    return row


def _inferred(value: Any) -> str | None:
    """The IR type a sample value suggests, or None for a null."""
    from bson import Binary, Decimal128, Int64, ObjectId

    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Int64):
        return "bigint"
    if isinstance(value, int):
        return "integer" if -(2**31) <= value < 2**31 else "bigint"
    if isinstance(value, float):
        return "double"
    if isinstance(value, Decimal128):
        return "numeric"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, Binary) and value.subtype in (3, 4):
        return "uuid"
    if isinstance(value, (str, ObjectId)):
        return "text"
    return "json"


def infer_columns(docs: list[dict]) -> list[OutputColumn]:
    """The output columns a preview's documents suggest, for the steward to confirm: one per
    field, a nested document's fields flattened (``a.b`` read into ``a_b``), an array as json. A
    field typed differently across the documents is json; one null in every document is text."""
    found: dict[str, set[str]] = {}

    def visit(doc: dict, prefix: str) -> None:
        for key, value in doc.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                visit(value, f"{path}.")
                continue
            types = found.setdefault(path, set())
            kind = _inferred(value)
            if kind is not None:
                types.add(kind)

    for doc in docs:
        visit(doc, "")
    columns = []
    for path, types in found.items():
        data_type = types.pop() if len(types) == 1 else ("text" if not types else "json")
        name = path.replace(".", "_")
        columns.append(OutputColumn(name, data_type, path if "." in path else None))
    return columns
