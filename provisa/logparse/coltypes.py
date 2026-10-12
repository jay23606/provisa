# Copyright (c) 2026 Kenneth Stott
# Canary: cb5ec7ed-2aac-46e6-810d-fa2e0791a646
#
# This source code is licensed under the Business Source License 1.1
"""Column types from a preview of values (REQ-1996), for a format whose records name their own
fields (JSON lines, logfmt): the narrowest type every value seen fits, string when none fits."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from provisa.logparse.base import ColumnType


def is_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return any(c in value for c in "T :") and value[:4].isdigit()


def _fits(value: Any) -> set[str]:
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, int):
        return {"integer", "float"}
    if isinstance(value, float):
        return {"float"}
    if isinstance(value, (dict, list)):
        return {"json"}
    if isinstance(value, str):
        text = value.strip()
        fits = set()
        if text.lstrip("-").isdigit():
            fits |= {"integer", "float"}
        else:
            try:
                float(text)
                fits.add("float")
            except ValueError:
                pass
        if text.lower() in ("true", "false"):
            fits.add("boolean")
        if is_timestamp(text):
            fits.add("timestamp")
        return fits
    return set()


def infer_type(values: list[Any]) -> ColumnType:
    seen = [v for v in values if v is not None and v != ""]
    if not seen:
        return "string"
    common = set.intersection(*(_fits(v) for v in seen))
    for kind in ("boolean", "integer", "float", "timestamp", "json"):
        if kind in common:
            return kind  # type: ignore[return-value]
    return "string"


def coerce(value: Any, kind: ColumnType) -> Any:
    """A value as the column's type; a value the type cannot hold raises ValueError."""
    if value is None or (isinstance(value, str) and value == ""):
        return None
    if kind == "string":
        return value if isinstance(value, str) else str(value)
    if kind == "integer":
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not an integer")
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "false"):
            return str(value).lower() == "true"
        raise ValueError(f"{value!r} is not a boolean")
    if kind == "timestamp":
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value  # json: kept as the structure it is
