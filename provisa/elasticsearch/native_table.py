# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A read of an Elasticsearch native-search table (REQ-2017), as a MongoDB pipeline table is read
(REQ-1980): the statement's arguments converted to their declared types, bound into the search,
the search run by the native reader (whatever the federation engine), and each row checked
against the table's output columns. The caller lands the rows for the engine to read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

from provisa.elasticsearch.native_query import QUERY_ARG

# Hits fetched per page of a search.
_BATCH_ROWS = 1000


def is_native_search_table(table: dict, source_types: dict[str, str]) -> bool:
    """Whether a registered table (a ``state.tables`` row) is an Elasticsearch native search."""
    return (
        bool(table.get("query_template"))
        and source_types.get(table["source_id"]) == "elasticsearch"
    )


def _arguments(table: dict, given: dict | None) -> dict[str, Any]:
    """Each declared argument with its converted value (None where the read gives none). A
    required argument left without a value was refused before this (REQ-1986)."""
    from provisa.compiler.naming import apply_sql_name
    from provisa.core.parameter_values import convert
    from provisa.core.parameters import parameter_name

    by_canon = {apply_sql_name(k.lstrip("_")): v for k, v in (given or {}).items()}
    out: dict[str, Any] = {}
    for col in table["columns"]:
        if col["native_filter_type"] != QUERY_ARG:
            continue
        name = parameter_name(col)
        value = by_canon.get(apply_sql_name(name.lstrip("_")))
        out[name] = convert(value, col["data_type"], table=table["table_name"], parameter=name)
    return out


def cache_arguments(table: dict, given: dict | None) -> dict[str, str]:
    """The arguments a read gives, by name, as text: what its landed rows are kept under."""
    return {k: str(v) for k, v in _arguments(table, given).items() if v is not None}


def row_batches(
    conn: Any, name: str, text: str, values: dict[str, Any], batch_rows: int
) -> Iterator[list[dict]]:
    """The documents a native search answers, bound with ``values``, in batches: one per bucket
    for a search with aggregations, one per hit otherwise."""
    from provisa.elasticsearch.fetch import search_aggregations, search_hits
    from provisa.elasticsearch.native_query import (
        bind,
        check,
        flatten_buckets,
        hit_document,
    )

    search = check(name, text, set(values))
    body = bind(search, values)
    if search.buckets:
        yield flatten_buckets(name, search_aggregations(conn, search.index, body))
        return
    for hits in search_hits(conn, search.index, body, batch_rows):
        yield [hit_document(hit) for hit in hits]


def _outputs(columns: list[dict]) -> list[Any]:
    from provisa.mongodb.pipeline_rows import OutputColumn

    return [
        OutputColumn(c["column_name"], c["data_type"], c.get("path"))
        for c in columns
        if c["native_filter_type"] is None
    ]


async def read(state: Any, table: dict, given: dict | None) -> Any:
    """Run ``table``'s search with the arguments ``given`` and return its checked rows."""
    from provisa.core.ir_types import to_ir
    from provisa.elasticsearch.fetch import ESConnection
    from provisa.federation.registry_view import registered_sources
    from provisa.mongodb.pipeline_rows import project
    from provisa.mongodb.pipeline_table import PipelineRead

    name = table["table_name"]
    values = _arguments(table, given)
    outputs = _outputs(table["columns"])
    found = [s for s in await registered_sources(state) if s.id == table["source_id"]]
    if not found:
        raise ValueError(f"Table {name!r}: its source {table['source_id']!r} is not registered")
    conn = ESConnection.from_source(found[0])

    def _run() -> list[dict]:
        return [
            # Elasticsearch holds a date as text in the document.
            project(name, doc, outputs, dates_as_text=True)
            for batch in row_batches(conn, name, table["query_template"], values, _BATCH_ROWS)
            for doc in batch
        ]

    rows = await asyncio.to_thread(_run)
    return PipelineRead(rows=rows, columns=[(c.name, to_ir(c.data_type)) for c in outputs])


def whole_batches(conn: Any, table: Any, batch_rows: int) -> Iterator[list[dict]]:
    """A native search with no arguments read whole, as a replica reads it: its checked rows in
    batches. ``table`` is the registry's view of it (columns with ``name``, ``data_type``,
    ``path``, ``native_filter_type``). A search with arguments has no whole table."""
    from provisa.mongodb.pipeline_rows import OutputColumn, project

    name = table.table_name
    if any(c.native_filter_type == QUERY_ARG for c in table.columns):
        raise ValueError(f"Table {name!r} is a function of its arguments: it has no whole table")
    outputs = [
        OutputColumn(c.name, c.data_type, c.path)
        for c in table.columns
        if c.native_filter_type is None
    ]
    for batch in row_batches(conn, name, table.query_template, {}, batch_rows):
        yield [project(name, doc, outputs, dates_as_text=True) for doc in batch]


def preview_columns(conn: Any, index: str, docs: list[dict], buckets: bool) -> list[Any]:
    """The output columns a preview suggests, for the steward to confirm. A bucket search's are
    its rows' (each key and metric); a hit search's are the index mapping's, restricted to the
    fields the hits hold, with the hit's id and score and the highlighted fields."""
    from provisa.core.ir_types import to_ir
    from provisa.elasticsearch.fetch import index_columns
    from provisa.mongodb.pipeline_rows import OutputColumn, infer_columns

    if buckets:
        return infer_columns(docs)
    present = {key for doc in docs for key in _paths(doc)}
    # The hit's own id and score, named apart from the documents' fields (GraphQL drops a
    # leading underscore, and a document may hold an id of its own).
    columns = [OutputColumn("hit_id", "text", "_id"), OutputColumn("hit_score", "double", "_score")]
    for field in index_columns(conn, index):
        if field["sourcePath"] in present:
            columns.append(OutputColumn(field["name"], to_ir(field["type"]), field["sourcePath"]))
    highlighted = sorted({k for doc in docs for k in doc if k.startswith("highlight_")})
    columns.extend(OutputColumn(k, "json") for k in highlighted)
    return columns


def _paths(doc: Any, prefix: str = "") -> Iterator[str]:
    """Every field path a document holds, a nested object's fields as ``a.b`` and the object
    itself as ``a``."""
    if not isinstance(doc, dict):
        return
    for key, value in doc.items():
        path = f"{prefix}{key}"
        yield path
        if isinstance(value, dict):
            yield from _paths(value, f"{path}.")
