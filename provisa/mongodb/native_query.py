# Copyright (c) 2026 Kenneth Stott
# Canary: 6d2e3892-b915-4af8-8cfb-cf35207b9b59
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A MongoDB table registered from an aggregation pipeline (REQ-1980).

The table's ``query_template`` holds the native query as one Extended JSON document,
``{"inputCollection": ..., "pipeline": [...]}``. An argument is a placeholder string value
``"{{name}}"`` anywhere in the pipeline, and a parameter of the table (``pipeline_arg``,
REQ-1986). Binding replaces each placeholder node of the parsed pipeline with the argument's
value, which the driver then encodes as BSON: a value is never written into the pipeline's text,
so it can only ever be a value. A pipeline table is read-only: a pipeline that writes ($out,
$merge) is refused.
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

PIPELINE_ARG = "pipeline_arg"
_PLACEHOLDER = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_EMBEDDED = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")
# The stages that write: a pipeline table only reads.
_WRITING_STAGES = frozenset({"$out", "$merge"})


class NativeQueryRefused(ValueError):
    """A pipeline table's native query that cannot be registered, said naming what is wrong."""

    code = "schema.mongodb_native_query_invalid"

    def __init__(self, table: str, reason: str) -> None:
        self.params = {"table": table, "reason": reason}
        super().__init__(f"Table {table!r}: {reason}")


@dataclass(frozen=True)
class NativeQuery:
    input_collection: str
    pipeline: list[dict]


def parse(table: str, text: str) -> NativeQuery:
    """The stored native query of ``table``: its input collection and its pipeline."""
    from bson import json_util

    try:
        doc = json_util.loads(text)
    except ValueError as exc:
        raise NativeQueryRefused(table, f"the native query is not Extended JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise NativeQueryRefused(table, "the native query is a document")
    unknown = set(doc) - {"inputCollection", "pipeline"}
    if unknown:
        raise NativeQueryRefused(
            table,
            f"the native query holds inputCollection and pipeline only, not {sorted(unknown)}",
        )
    collection = doc.get("inputCollection")
    if not isinstance(collection, str) or not collection:
        raise NativeQueryRefused(table, "the native query names its inputCollection")
    pipeline = doc.get("pipeline")
    if not isinstance(pipeline, list) or not all(
        isinstance(stage, dict) and len(stage) == 1 for stage in pipeline
    ):
        raise NativeQueryRefused(table, "the pipeline is a list of stages, each of one operator")
    return NativeQuery(collection, pipeline)


def _walk(node: Any, path: str):
    """Every (path, key, value) of ``node``, keys of documents and items of arrays."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield path, None, value
            yield from _walk(value, f"{path}[{i}]")


def placeholders(table: str, query: NativeQuery) -> set[str]:
    """The arguments ``query`` names. A placeholder inside a longer string is refused: it could
    only be filled by writing a value into text."""
    found: set[str] = set()
    for path, key, value in _walk(query.pipeline, "pipeline"):
        if key in _WRITING_STAGES:
            raise NativeQueryRefused(
                table, f"a pipeline table only reads; {key} at {path} writes to the database"
            )
        if isinstance(value, str):
            whole = _PLACEHOLDER.match(value)
            if whole:
                found.add(whole.group(1))
            elif _EMBEDDED.search(value):
                raise NativeQueryRefused(
                    table,
                    f"the placeholder in {value!r} at {path} is inside a longer string; an "
                    "argument is a whole value",
                )
    return found


def check(table: str, text: str, arguments: set[str]) -> NativeQuery:
    """``text`` parsed and checked against the table's declared arguments (its ``pipeline_arg``
    parameters, by name): each placeholder names one, and each one is used."""
    query = parse(table, text)
    named = placeholders(table, query)
    undeclared = sorted(named - arguments)
    if undeclared:
        raise NativeQueryRefused(
            table, f"the pipeline names {undeclared}, which the table declares as no argument"
        )
    unused = sorted(arguments - named)
    if unused:
        raise NativeQueryRefused(table, f"the arguments {unused} appear nowhere in the pipeline")
    return query


def _bson(value: Any, data_type: str) -> Any:
    """A converted parameter value (``provisa.core.parameter_values``) as the BSON value the
    driver writes for its type."""
    from bson import Binary, Decimal128, Int64
    from bson.binary import UuidRepresentation

    base = data_type.strip().lower().split("(")[0].strip()
    if value is None:
        return None
    if isinstance(value, list):
        inner = data_type.strip()[len("array(") : -1]
        return [_bson(v, inner) for v in value]
    if base in ("bigint", "int8"):
        return Int64(value)
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, uuid.UUID):
        return Binary.from_uuid(value, UuidRepresentation.STANDARD)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return value


def bind(query: NativeQuery, values: dict[str, tuple[Any, str]]) -> list[dict]:
    """The pipeline with each placeholder replaced by its argument's value, as BSON:
    ``values`` maps an argument's name to its converted value and its declared type. An argument
    with no value binds null."""

    def fill(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str):
            whole = _PLACEHOLDER.match(node)
            if whole:
                value, data_type = values[whole.group(1)]
                return _bson(value, data_type)
        return node

    return fill(copy.deepcopy(query.pipeline))


def check_table(table: Any) -> NativeQuery:
    """A pipeline table as registered (a ``core.models.Table``): its native query checked against
    its arguments, every column typed, and none of the settings a pipeline cannot take."""
    name = table.table_name
    arguments = {
        c.name.removeprefix("_nf_") for c in table.columns if c.native_filter_type == PIPELINE_ARG
    }
    other = sorted(
        {c.native_filter_type for c in table.columns if c.native_filter_type} - {PIPELINE_ARG}
    )
    if other:
        raise NativeQueryRefused(name, f"a pipeline's parameters are pipeline_arg, not {other}")
    untyped = [c.name for c in table.columns if not c.data_type]
    if untyped:
        raise NativeQueryRefused(name, f"the columns {untyped} have no data type")
    if table.change_signal == "native":
        raise NativeQueryRefused(
            name, "a change stream watches a collection, not a pipeline's output; use a TTL"
        )
    if table.row_materialize:
        raise NativeQueryRefused(name, "a pipeline's rows have no key to be fetched by")
    return check(name, table.query_template, arguments)


def native_query_text(binding: dict) -> str:
    """A pipeline command's binding (REQ-1988) as native-query text."""
    from bson import json_util

    return json_util.dumps(binding)


def check_command(name: str, binding: dict, arguments: list[dict]) -> NativeQuery:
    """A pipeline command as registered (REQ-1988): its native query parses, names only its
    arguments and uses each, and only reads."""
    return check(name, native_query_text(binding), {a["name"] for a in arguments})
