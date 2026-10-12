# Copyright (c) 2026 Kenneth Stott
# Canary: 9da7d380-1ac0-41d0-8786-ecdc8faf6bc9
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A table of a Cosmos DB source (REQ-1982): a container, or a Cosmos SQL query.

A container table is named for its container. A query table holds ``{"container": ...,
"query": "SELECT ... FROM c WHERE c.x = @x"}`` in its ``query_template``; each ``@name`` is a
parameter of the table (``query_arg``, REQ-1986) whose value the SDK sends beside the query's
text, never inside it. Either kind may expose the container's partition key as a parameter
(``partition_key``): given, the read is one partition's. A table with parameters is read per
statement, under the arguments given (the materialization step); one without is read whole,
as a replica reads it.

Every value is converted strictly to its parameter's type first (``core.parameter_values``);
every returned document is checked against the table's columns, a date or timestamp column
reading an ISO 8601 string, which is how Cosmos holds one.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from provisa.core.parameters import parameter_name

QUERY_ARG = "query_arg"
PARTITION_KEY = "partition_key"
_PARAM = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_BATCH_ROWS = 1000


class CosmosTableRefused(ValueError):
    """A Cosmos DB table that cannot be registered, said naming what is wrong."""

    code = "schema.cosmosdb_table_invalid"

    def __init__(self, table: str, reason: str) -> None:
        self.params = {"table": table, "reason": reason}
        super().__init__(f"Table {table!r}: {reason}")


@dataclass(frozen=True)
class CosmosQuery:
    container: str
    query: str


def parse(table: str, text: str) -> CosmosQuery:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise CosmosTableRefused(table, f"the query is not JSON: {exc}") from exc
    if not isinstance(doc, dict) or set(doc) != {"container", "query"}:
        raise CosmosTableRefused(table, 'the query is {"container": ..., "query": ...}')
    if not isinstance(doc["container"], str) or not doc["container"]:
        raise CosmosTableRefused(table, "the query names its container")
    if not isinstance(doc["query"], str) or not doc["query"].strip():
        raise CosmosTableRefused(table, "the query's text is empty")
    return CosmosQuery(doc["container"], doc["query"])


def _kinds(table: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for c in _columns(table):
        kind = _get(c, "native_filter_type")
        if kind is not None:
            out.setdefault(kind, []).append(c)
    return out


def _get(column: Any, key: str) -> Any:
    return column.get(key) if isinstance(column, dict) else getattr(column, key, None)


def _columns(table: Any) -> list[Any]:
    return list(_get(table, "columns") or [])


def check_table(table: Any) -> CosmosQuery | None:
    """A Cosmos table as registered: its query (if any) names exactly its declared query
    arguments; it has at most one partition key parameter and no parameter of another kind; every
    column is typed. Returns the parsed query, or None for a container table."""
    name = _get(table, "table_name")
    kinds = _kinds(table)
    other = sorted(set(kinds) - {QUERY_ARG, PARTITION_KEY})
    if other:
        raise CosmosTableRefused(
            name, f"a Cosmos table's parameters are query_arg or partition_key, not {other}"
        )
    if len(kinds.get(PARTITION_KEY, [])) > 1:
        raise CosmosTableRefused(name, "a table has one partition key parameter")
    untyped = [
        _get(c, "name") or _get(c, "column_name")
        for c in _columns(table)
        if not _get(c, "data_type")
    ]
    if untyped:
        raise CosmosTableRefused(name, f"the columns {untyped} have no data type")
    text = _get(table, "query_template")
    if _get(table, "change_signal") == "native" and (text or kinds):
        raise CosmosTableRefused(
            name,
            "the change feed follows a whole container; a table read under arguments has none "
            "to follow -- use a TTL",
        )
    declared = {parameter_name(c) for c in kinds.get(QUERY_ARG, [])}
    if not text:
        if declared:
            raise CosmosTableRefused(name, "a container table has no query to take arguments")
        return None
    query = parse(name, text)
    named = set(_PARAM.findall(query.query))
    if named - declared:
        raise CosmosTableRefused(
            name,
            f"the query names {sorted(named - declared)}, which the table declares as no argument",
        )
    if declared - named:
        raise CosmosTableRefused(
            name, f"the arguments {sorted(declared - named)} appear nowhere in the query"
        )
    return query


def _json_value(value: Any) -> Any:
    """A converted parameter value as the JSON value Cosmos is sent."""
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _arguments(table: dict, given: dict | None) -> dict[str, tuple[Any, Any]]:
    """Each parameter of ``table`` with its converted value (None where none is given) and its
    column."""
    from provisa.compiler.naming import apply_sql_name
    from provisa.core.parameter_values import convert

    by_canon = {apply_sql_name(k.lstrip("_")): v for k, v in (given or {}).items()}
    out: dict[str, tuple[Any, Any]] = {}
    for col in table["columns"]:
        if col["native_filter_type"] not in (QUERY_ARG, PARTITION_KEY):
            continue
        name = parameter_name(col)
        value = by_canon.get(apply_sql_name(name.lstrip("_")))
        out[name] = (
            convert(value, col["data_type"], table=table["table_name"], parameter=name),
            col,
        )
    return out


def cache_arguments(table: dict, given: dict | None) -> dict[str, str]:
    """The arguments a read gives, by name, as text: what its landed rows are kept under."""
    return {k: str(v) for k, (v, _) in _arguments(table, given).items() if v is not None}


def has_parameters(table: dict) -> bool:
    return any(c["native_filter_type"] in (QUERY_ARG, PARTITION_KEY) for c in table["columns"])


def plan(table: dict, given: dict | None) -> tuple[str, str, list[dict], Any]:
    """What a read of ``table`` sends: its container, its query, the query's parameters and the
    partition key value (None for a read across partitions)."""
    query = check_table(table)
    arguments = _arguments(table, given)
    partition = next(
        (v for v, col in arguments.values() if col["native_filter_type"] == PARTITION_KEY), None
    )
    if query is None:
        return table["table_name"], "SELECT * FROM c", [], _json_value(partition)
    parameters = [
        {"name": f"@{name}", "value": _json_value(value)}
        for name, (value, col) in arguments.items()
        if col["native_filter_type"] == QUERY_ARG
    ]
    return query.container, query.query, parameters, _json_value(partition)


async def read(state: Any, table: dict, given: dict | None) -> Any:
    """Read ``table`` with the arguments ``given`` and return its checked rows."""
    from provisa.core.ir_types import to_ir
    from provisa.cosmosdb.fetch import CosmosConnection, iter_query_batches
    from provisa.federation.registry_view import registered_sources
    from provisa.mongodb.pipeline_rows import OutputColumn, project
    from provisa.mongodb.pipeline_table import PipelineRead

    name = table["table_name"]
    container, query, parameters, partition = plan(table, given)
    outputs = [
        OutputColumn(c["column_name"], c["data_type"], c.get("path"))
        for c in table["columns"]
        if c["native_filter_type"] is None
    ]
    found = [s for s in await registered_sources(state) if s.id == table["source_id"]]
    if not found:
        raise ValueError(f"Table {name!r}: its source {table['source_id']!r} is not registered")
    conn = CosmosConnection.from_source(found[0])

    def _run() -> list[dict]:
        return [
            project(name, doc, outputs, dates_as_text=True)
            for batch in iter_query_batches(
                conn, container, query, parameters, _BATCH_ROWS, partition
            )
            for doc in batch
        ]

    rows = await asyncio.to_thread(_run)
    return PipelineRead(rows=rows, columns=[(c.name, to_ir(c.data_type)) for c in outputs])
