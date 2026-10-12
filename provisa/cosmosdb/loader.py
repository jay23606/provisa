# Copyright (c) 2026 Kenneth Stott
# Canary: d8b0e789-ce4a-484c-9cf0-296fd35f7619
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The row loaders of a Cosmos DB source (REQ-1982), as ``events.source_loader`` builds them for
the other natively read sources: a whole table (its replica, its residency), and a keyed fetch
(``row_materialize``). A table with parameters is read per statement instead, under the
statement's arguments (``cosmosdb.table``), and has no whole table to load.

The keyed fetch is a point read per key where the table's key is the document ``id`` and its
partition key -- the cheapest read Cosmos serves; any other key is one parameterized query.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

_BATCH_ROWS = 1000


def _outputs(table: Any) -> list[Any]:
    from provisa.mongodb.pipeline_rows import OutputColumn

    return [
        OutputColumn(c.name, c.data_type, getattr(c, "path", None))
        for c in table.columns
        if getattr(c, "native_filter_type", None) is None
    ]


def _whole_batches(source: Any, table: Any, batch_rows: int):
    from provisa.cosmosdb.fetch import CosmosConnection, iter_container_batches
    from provisa.mongodb.pipeline_rows import project

    if getattr(table, "query_template", None) or any(
        getattr(c, "native_filter_type", None) for c in table.columns
    ):
        raise ValueError(
            f"Table {table.table_name!r} is read under the arguments of each statement: it has no "
            "whole table to load"
        )
    conn = CosmosConnection.from_source(source)
    outputs = _outputs(table)
    for batch in iter_container_batches(conn, table.table_name, batch_rows):
        yield [project(table.table_name, doc, outputs, dates_as_text=True) for doc in batch]


def make_cosmosdb_loader() -> Any:
    """The whole-table load of a Cosmos DB container table, with its replica source."""

    async def _load(source: Any, table: Any) -> list[dict]:
        return await asyncio.to_thread(
            lambda: [r for b in _whole_batches(source, table, _BATCH_ROWS) for r in b]
        )

    def _replica_source(source: Any, table: Any, columns: list[tuple[str, str]]) -> Any:
        from provisa.federation.replica_source import BlockingCursorSource

        return BlockingCursorSource(
            lambda batch_rows: _whole_batches(source, table, batch_rows), columns
        )

    _load.replica_source = _replica_source  # type: ignore[attr-defined]
    return _load


def _field(path: str) -> str:
    """A partition key path (``/customerId``, ``/address/city``) as a document field path."""
    return path.strip("/").replace("/", ".")


def make_cosmosdb_keyed_loader() -> Any:
    """The keyed fetch of a Cosmos DB container table (REQ-1865 row_materialize)."""
    from provisa.cosmosdb.fetch import (
        CosmosConnection,
        iter_query_batches,
        partition_key_paths,
        read_points,
    )
    from provisa.mongodb.pipeline_rows import project

    async def _load(
        source: Any, table: Any, pk_columns: list[str], keys: list[tuple[Any, ...]]
    ) -> list[dict]:
        if not keys:
            return []
        conn = CosmosConnection.from_source(source)
        container = table.table_name
        outputs = _outputs(table)

        def _run() -> list[dict]:
            paths = [_field(p) for p in partition_key_paths(conn, container)]
            # A point read needs the id and the partition key value: the key is exactly those.
            if len(paths) == 1 and set(pk_columns) == {"id", paths[0]}:
                at = {c: i for i, c in enumerate(pk_columns)}
                pairs = [(k[at["id"]], k[at[paths[0]]]) for k in keys]
                docs = read_points(conn, container, pairs)
            else:
                clauses, parameters = [], []
                for i, key in enumerate(keys):
                    terms = []
                    for j, column in enumerate(pk_columns):
                        name = f"@k{i}_{j}"
                        terms.append(f"c[{json.dumps(column)}] = {name}")
                        parameters.append({"name": name, "value": key[j]})
                    clauses.append("(" + " AND ".join(terms) + ")")
                query = "SELECT * FROM c WHERE " + " OR ".join(clauses)
                docs = [
                    doc
                    for batch in iter_query_batches(conn, container, query, parameters, _BATCH_ROWS)
                    for doc in batch
                ]
            return [project(container, doc, outputs, dates_as_text=True) for doc in docs]

        return await asyncio.to_thread(_run)

    return _load
