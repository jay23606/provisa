# Copyright (c) 2026 Kenneth Stott
# Canary: 9773fa09-6de4-4776-bd15-42db7b38a3a3
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A parameter's value as its declared type (REQ-1980, REQ-1986).

A caller gives a parameter's value as SQL gives it (a literal, often text, or a bound value) or as
GraphQL gives it (a typed argument). Before the value reaches a source it is converted, strictly,
to the parameter's declared type: an IR type, or ``array(<IR type>)``. A value that does not
convert is refused, naming the table, the parameter and the type; nothing is coerced loosely and
nothing is guessed. The result is a plain Python value -- each source's binder turns it into the
source's own encoding (a MongoDB pipeline binds it as BSON).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_INTEGERS = frozenset({"smallint", "integer", "int", "bigint", "int2", "int4", "int8"})
_FLOATS = frozenset({"float", "double", "real", "float4", "float8", "double precision"})
_TEXTS = frozenset({"text", "varchar", "char", "string"})


class ParameterValueRefused(ValueError):
    """A parameter's value that is not of the parameter's declared type."""

    def __init__(self, table: str, parameter: str, data_type: str, value: Any) -> None:
        self.params = {"table": table, "parameter": parameter, "type": data_type}
        shown = repr(value)
        if len(shown) > 80:
            shown = shown[:77] + "..."
        super().__init__(
            f"Table {table!r}: parameter {parameter!r} takes a value of type {data_type}; "
            f"{shown} is not one"
        )


def element_type(data_type: str) -> str | None:
    """``T`` for an ``array(T)`` type, else None."""
    t = data_type.strip().lower()
    if t.startswith("array(") and t.endswith(")"):
        return t[len("array(") : -1].strip()
    return None


def _base(data_type: str) -> str:
    return data_type.strip().lower().split("(")[0].strip()


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("a boolean is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    raise ValueError("not an integer")


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError("not a number")


def _numeric(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError("not a number") from exc
    raise ValueError("not a number")


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("not a boolean")


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value.strip())
    else:
        raise ValueError("not a timestamp")
    # A time with no zone is UTC, as the engines read one.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        raise ValueError("a timestamp is not a date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError("not a date")


def _json(value: Any) -> Any:
    from bson import json_util

    # Extended JSON, so a value can name a type JSON has no word for ({"$oid": ...}).
    if isinstance(value, str):
        return json_util.loads(value)
    if isinstance(value, (dict, list)):
        return json_util.loads(json.dumps(value))
    raise ValueError("not a JSON document")


def _scalar(value: Any, base: str) -> Any:
    if base in _INTEGERS:
        return _integer(value)
    if base in _FLOATS:
        return _float(value)
    if base in ("numeric", "decimal"):
        return _numeric(value)
    if base in ("boolean", "bool"):
        return _boolean(value)
    if base in ("timestamp", "timestamptz", "datetime"):
        return _timestamp(value)
    if base == "date":
        return _date(value)
    if base == "uuid":
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if base in ("json", "jsonb"):
        return _json(value)
    if base in _TEXTS:
        if not isinstance(value, str):
            raise ValueError("not text")
        return value
    raise ValueError(f"no parameter takes the type {base!r}")


def convert(value: Any, data_type: str, *, table: str, parameter: str) -> Any:
    """``value`` as ``data_type``, strictly: an IR type, or ``array(T)`` whose value is a list
    (or JSON text holding one) with each element converted as ``T``. None stays None -- an
    absent value is no value."""
    if value is None:
        return None
    try:
        element = element_type(data_type)
        if element is None:
            return _scalar(value, _base(data_type))
        items = json.loads(value) if isinstance(value, str) else value
        if not isinstance(items, (list, tuple)):
            raise ValueError("not an array")
        return [None if v is None else _scalar(v, _base(element)) for v in items]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ParameterValueRefused(table, parameter, data_type, value) from exc
