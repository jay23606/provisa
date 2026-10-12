# Copyright (c) 2026 Kenneth Stott
# Canary: aa15c238-7971-4e7b-9585-99777e3cee0f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What Register Table offers of a Qdrant source (REQ-1983): one schema, its collections as
tables, and a collection's columns: the point's id (its key), the payload's fields -- an indexed
field typed by its index, any other as its points suggest, nested fields flattened with their
path -- and one column per vector, last."""

# Requirements: REQ-1983
from __future__ import annotations

import asyncio
from typing import Any

# The one schema a Qdrant source has, as an Elasticsearch source's: Qdrant groups collections in
# nothing.
SCHEMA = "default"
# Points read to suggest a collection's payload columns.
SAMPLE_POINTS = 20

# Qdrant's payload index types (PayloadSchemaType) as IR types.
_INDEX_TYPES = {
    "keyword": "text",
    "text": "text",
    "uuid": "text",
    "integer": "bigint",
    "float": "double",
    "bool": "boolean",
    "datetime": "timestamp",
    "geo": "json",
}


async def _source(state: Any, source_id: str) -> Any:
    from provisa.federation.registry_view import registered_sources

    found = [s for s in await registered_sources(state) if s.id == source_id]
    return found[0] if found else None


async def schemas(state: Any, source_id: str) -> list[str] | None:
    source = await _source(state, source_id)
    return None if source is None else [SCHEMA]


async def collections(state: Any, source_id: str) -> list[str] | None:
    from provisa.qdrant.fetch import QdrantConnection, list_collections

    source = await _source(state, source_id)
    if source is None:
        return None
    return await asyncio.to_thread(list_collections, QdrantConnection.from_source(source))


def _id_type(docs: list[dict]) -> str:
    """A point id is an unsigned integer or a UUID: bigint when every sampled id is an integer."""
    from provisa.qdrant.fetch import ID_PATH

    ids = [d[ID_PATH] for d in docs]
    return "bigint" if ids and all(isinstance(i, int) for i in ids) else "text"


async def columns(state: Any, source_id: str, collection: str) -> list[dict] | None:
    """The suggested columns of ``collection``: ``{name, data_type, path, is_primary_key}``."""
    from provisa.mongodb.pipeline_rows import infer_columns
    from provisa.qdrant.fetch import (
        ID_PATH,
        QdrantConnection,
        collection_shape,
        sample,
        vector_path,
    )

    source = await _source(state, source_id)
    if source is None:
        return None
    conn = QdrantConnection.from_source(source)

    def _read() -> tuple[list[dict], Any]:
        return sample(conn, collection, SAMPLE_POINTS), collection_shape(conn, collection)

    docs, shape = await asyncio.to_thread(_read)
    payloads = [{k: v for k, v in d.items() if not k.startswith("@")} for d in docs]
    out = [{"name": "id", "data_type": _id_type(docs), "path": ID_PATH, "is_primary_key": True}]
    seen = {"id"}
    for c in infer_columns(payloads):
        path = c.path or c.name
        indexed = _INDEX_TYPES.get(shape.indexed.get(path, ""))
        out.append(
            {
                "name": c.name,
                "data_type": indexed or c.data_type,
                "path": c.path,
                "is_primary_key": False,
            }
        )
        seen.add(c.name)
    # An indexed field no sampled point holds is still the collection's.
    for path, kind in sorted(shape.indexed.items()):
        name = path.replace(".", "_")
        if name not in seen and kind in _INDEX_TYPES:
            out.append(
                {
                    "name": name,
                    "data_type": _INDEX_TYPES[kind],
                    "path": path if "." in path else None,
                    "is_primary_key": False,
                }
            )
            seen.add(name)
    for vector in sorted(shape.vectors):
        name = f"{vector}_vector" if vector else "vector"
        out.append(
            {
                "name": name,
                "data_type": "json",
                "path": vector_path(vector),
                "is_primary_key": False,
            }
        )
    return out


async def vectors(state: Any, source_id: str, collection: str) -> list[dict] | None:
    """A collection's vectors -- ``{name, size, distance}``, the unnamed one named ``""`` -- for a
    search's form: what ``using`` may name, how long a query vector is, and what its score is."""
    from provisa.qdrant.fetch import QdrantConnection, collection_shape

    source = await _source(state, source_id)
    if source is None:
        return None
    shape = await asyncio.to_thread(
        collection_shape, QdrantConnection.from_source(source), collection
    )
    return [
        {"name": n, "size": size, "distance": distance}
        for n, (size, distance) in sorted(shape.vectors.items())
    ]
