# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The row loaders of a Qdrant source (REQ-1983), as ``events.source_loader`` builds them for the
other natively read sources: a whole collection (its replica), and a keyed fetch
(``row_materialize``). A search is read per statement instead, under the statement's arguments
(``qdrant.table``), and has no whole table to load.

The keyed fetch is one ``retrieve`` where the key is the point id -- the cheapest read Qdrant
serves; any other key is one filtered scroll.
"""

# Requirements: REQ-1983
from __future__ import annotations

import asyncio
from typing import Any

_BATCH_ROWS = 1000


def _outputs(table: Any) -> list[Any]:
    from provisa.mongodb.pipeline_rows import OutputColumn

    return [
        OutputColumn(c.name, c.data_type, getattr(c, "path", None))
        for c in table.columns
        if getattr(c, "native_filter_type", None) is None
    ]


def _vectors(outputs: list[Any]) -> bool | list[str]:
    from provisa.qdrant.fetch import vectors_read

    return vectors_read([o.path or o.name for o in outputs])


def _whole_batches(source: Any, table: Any, batch_rows: int):
    from provisa.mongodb.pipeline_rows import project
    from provisa.qdrant.fetch import QdrantConnection, iter_collection_batches

    if getattr(table, "query_template", None):
        raise ValueError(
            f"Table {table.table_name!r} is a search, read under the arguments of each statement: "
            "it has no whole table to load"
        )
    conn = QdrantConnection.from_source(source)
    outputs = _outputs(table)
    for batch in iter_collection_batches(conn, table.table_name, batch_rows, _vectors(outputs)):
        yield [project(table.table_name, doc, outputs, dates_as_text=True) for doc in batch]


def make_qdrant_loader() -> Any:
    """The whole-collection load of a Qdrant collection table, with its replica source."""

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


def make_qdrant_keyed_loader() -> Any:
    """The keyed fetch of a Qdrant collection table (REQ-1865 row_materialize)."""
    from provisa.mongodb.pipeline_rows import project
    from provisa.qdrant.fetch import ID_PATH, QdrantConnection, retrieve, scroll_matching

    async def _load(
        source: Any, table: Any, pk_columns: list[str], keys: list[tuple[Any, ...]]
    ) -> list[dict]:
        if not keys:
            return []
        conn = QdrantConnection.from_source(source)
        collection = table.table_name
        outputs = _outputs(table)
        paths = {o.name: o.path or o.name for o in outputs}
        vectors = _vectors(outputs)

        def _run() -> list[dict]:
            if [paths[c] for c in pk_columns] == [ID_PATH]:
                docs = retrieve(conn, collection, [k[0] for k in keys], vectors)
            else:
                # One clause per key, each matching every key column's payload field.
                query_filter = {
                    "should": [
                        {
                            "must": [
                                {"key": paths[c], "match": {"value": key[j]}}
                                for j, c in enumerate(pk_columns)
                            ]
                        }
                        for key in keys
                    ]
                }
                docs = scroll_matching(conn, collection, query_filter, _BATCH_ROWS, vectors)
            return [project(collection, doc, outputs, dates_as_text=True) for doc in docs]

        return await asyncio.to_thread(_run)

    return _load
