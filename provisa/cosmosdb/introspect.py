# Copyright (c) 2026 Kenneth Stott
# Canary: 5fc02629-cb66-408b-9505-d9319c97ff17
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What Register Table offers of a Cosmos DB source (REQ-1982): its database as the one schema,
its containers as tables, and a container's columns as its documents suggest them -- nested
fields flattened with their path -- with the container's partition key as an optional
parameter, which a steward may make required."""

from __future__ import annotations

import asyncio
from typing import Any

# Documents read to suggest a container's columns.
SAMPLE_DOCUMENTS = 20


async def _source(state: Any, source_id: str) -> Any:
    from provisa.federation.registry_view import registered_sources

    found = [s for s in await registered_sources(state) if s.id == source_id]
    return found[0] if found else None


async def schemas(state: Any, source_id: str) -> list[str] | None:
    source = await _source(state, source_id)
    return None if source is None else [source.database]


async def containers(state: Any, source_id: str) -> list[str] | None:
    from provisa.cosmosdb.fetch import CosmosConnection, list_containers

    source = await _source(state, source_id)
    if source is None:
        return None
    return await asyncio.to_thread(list_containers, CosmosConnection.from_source(source))


async def columns(state: Any, source_id: str, container: str) -> list[dict] | None:
    """The suggested columns of ``container``: ``{name, data_type, path, native_filter_type,
    native_filter_required}``, the partition key parameter last."""
    from provisa.cosmosdb.fetch import CosmosConnection, partition_key_paths, sample
    from provisa.cosmosdb.loader import _field
    from provisa.mongodb.pipeline_rows import infer_columns

    source = await _source(state, source_id)
    if source is None:
        return None
    conn = CosmosConnection.from_source(source)

    def _read() -> tuple[list[dict], list[str]]:
        return sample(conn, container, SAMPLE_DOCUMENTS), partition_key_paths(conn, container)

    docs, paths = await asyncio.to_thread(_read)
    suggested = infer_columns(docs)
    out = [
        {
            "name": c.name,
            "data_type": c.data_type,
            "path": c.path,
            "native_filter_type": None,
            "native_filter_required": None,
        }
        for c in suggested
    ]
    by_path = {c.path or c.name: c for c in suggested}
    for path in paths:
        field = _field(path)
        typed = by_path.get(field)
        out.append(
            {
                "name": "_nf_" + field.replace(".", "_"),
                "data_type": typed.data_type if typed is not None else "text",
                "path": field if "." in field else None,
                "native_filter_type": "partition_key",
                # Optional: a steward may make it required, so no read spans every partition.
                "native_filter_required": False,
            }
        )
    return out
