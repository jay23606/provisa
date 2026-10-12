# Copyright (c) 2026 Kenneth Stott
# Canary: ad7cb300-5a7f-4937-a662-ec8ac7f97d54
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Register Table on a query-API source (REQ-1670 neo4j, REQ-1683 sparql): the per-type preview
behind the form and the endpoint persistence the ``registerTable``/``updateTable`` mutations run.

A query-API source has no tables to list — its table IS a query projection — so the form previews
the query (rows + inferred column types), the operator names the table, and registration writes
the same ``api_sources``/``api_endpoints`` rows config load writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from provisa.core.schema_org import sources

if TYPE_CHECKING:
    from provisa.api.admin.types import MutationResult, QueryPreviewType
    from provisa.core.database import Connection
    from provisa.core.models import Table

QUERY_API_TYPES = frozenset({"neo4j", "sparql"})


async def source_row(conn: "Connection", source_id: str) -> dict[str, Any] | None:
    res = await conn.execute_core(
        select(
            sources.c.id, sources.c.type, sources.c.host, sources.c.port, sources.c.database
        ).where(sources.c.id == source_id)
    )
    row = res.fetchone()
    return dict(row._mapping) if row is not None else None


async def preview_sparql(conn: "Connection", source_id: str, query: str) -> "QueryPreviewType":
    """Run the SPARQL SELECT (LIMIT 5) against the source's endpoint and infer the columns —
    every SPARQL binding is a string, so the columns are ``text``."""
    import httpx

    from provisa.api.admin.types import QueryPreviewColumnType, QueryPreviewType
    from provisa.sparql.persist import sparql_config_from_source
    from provisa.sparql.source import extract_variables, probe_endpoint

    row = await source_row(conn, source_id)
    if row is None or row["type"] != "sparql":
        return QueryPreviewType(error=f"{source_id!r} is not a registered sparql source")
    cfg, _ = sparql_config_from_source(source_id=source_id, endpoint_url=row["host"])
    try:
        rows = await probe_endpoint(cfg, query)
    except (httpx.HTTPError, ValueError) as exc:
        return QueryPreviewType(error=f"{type(exc).__name__}: {exc}")
    names = list(rows[0].keys()) if rows else extract_variables(query)
    if not names:
        return QueryPreviewType(
            error="The query returned no rows and names no SELECT variables; columns cannot be inferred."
        )
    return QueryPreviewType(
        rows=list(rows),
        columns=[QueryPreviewColumnType(name=n, data_type="text") for n in names],
    )


# Documents a pipeline preview returns.
PREVIEW_ROWS = 5


async def preview_pipeline(
    conn: "Connection", source_id: str, native_query: str, arguments: list[dict]
) -> "QueryPreviewType":
    """REQ-1980: run a native query on a MongoDB source with sample ``arguments`` (each
    ``{name, dataType, value}``) and return up to five documents and the columns they suggest.
    Failures come back as ``error``: a half-written pipeline is the normal state of the editor."""
    import asyncio
    import json

    from bson import json_util

    from provisa.api.admin.types import QueryPreviewColumnType, QueryPreviewType
    from provisa.core.parameter_values import convert
    from provisa.federation.registry_view import registered_sources
    from provisa.mongodb.fetch import MongoConnection, aggregate_row_batches
    from provisa.mongodb.native_query import bind, check
    from provisa.mongodb.pipeline_rows import infer_columns

    from provisa.api.app import state

    row = await source_row(conn, source_id)
    if row is None or row["type"] != "mongodb":
        return QueryPreviewType(error=f"{source_id!r} is not a registered mongodb source")
    try:
        values = {
            a["name"]: (
                convert(a.get("value"), a["dataType"], table="preview", parameter=a["name"]),
                a["dataType"],
            )
            for a in arguments
        }
        query = check("preview", native_query, set(values))
        pipeline = [*bind(query, values), {"$limit": PREVIEW_ROWS}]
        source = next(s for s in await registered_sources(state, conn) if s.id == source_id)
        mongo = MongoConnection.from_source(source)
        database = source.database

        def _run() -> list[dict]:
            return [
                doc
                for batch in aggregate_row_batches(
                    mongo, database, query.input_collection, pipeline, PREVIEW_ROWS
                )
                for doc in batch
            ]

        docs = await asyncio.to_thread(_run)
    except Exception as exc:  # allow-blind-except: a preview reports every failure as its error
        return QueryPreviewType(error=f"{type(exc).__name__}: {exc}")
    return QueryPreviewType(
        rows=[
            json.loads(json_util.dumps(d, json_options=json_util.RELAXED_JSON_OPTIONS))
            for d in docs
        ],
        columns=[
            QueryPreviewColumnType(name=c.name, data_type=c.data_type, path=c.path)
            for c in infer_columns(docs)
        ],
    )


async def preview_cosmos_query(
    conn: "Connection", source_id: str, native_query: str, arguments: list[dict]
) -> "QueryPreviewType":
    """REQ-1982: run a Cosmos DB query table's query ({"container", "query"}) with sample
    ``arguments`` (each ``{name, dataType, value}``, sent as the query's @parameters) and return
    up to five documents and the columns they suggest. Failures come back as ``error``."""
    import asyncio
    import json

    from provisa.api.admin.types import QueryPreviewColumnType, QueryPreviewType
    from provisa.cosmosdb.fetch import CosmosConnection, iter_query_batches
    from provisa.cosmosdb.table import json_value, parse
    from provisa.core.parameter_values import convert
    from provisa.federation.registry_view import registered_sources
    from provisa.mongodb.pipeline_rows import infer_columns

    from provisa.api.app import state

    row = await source_row(conn, source_id)
    if row is None or row["type"] != "cosmosdb":
        return QueryPreviewType(error=f"{source_id!r} is not a registered cosmosdb source")
    try:
        query = parse("preview", native_query)
        parameters = [
            {
                "name": f"@{a['name']}",
                "value": json_value(
                    convert(a.get("value"), a["dataType"], table="preview", parameter=a["name"])
                ),
            }
            for a in arguments
        ]
        source = next(s for s in await registered_sources(state, conn) if s.id == source_id)
        cosmos = CosmosConnection.from_source(source)
        docs = await asyncio.to_thread(
            lambda: next(
                iter_query_batches(cosmos, query.container, query.query, parameters, PREVIEW_ROWS),
                [],
            )[:PREVIEW_ROWS]
        )
    except Exception as exc:  # allow-blind-except: a preview reports every failure as its error
        return QueryPreviewType(error=f"{type(exc).__name__}: {exc}")
    return QueryPreviewType(
        rows=[json.loads(json.dumps(d, default=str)) for d in docs],
        columns=[
            QueryPreviewColumnType(name=c.name, data_type=c.data_type, path=c.path)
            for c in infer_columns(docs)
        ],
    )


async def pipeline_table_refusal(conn: "Connection", model: "Table") -> "MutationResult | None":
    """REQ-1980: a MongoDB table registered with a native query is a pipeline table, checked
    before its row lands: the query parses, names only its declared arguments and uses each, and
    only reads. None for every other table."""
    from provisa.api.admin.types import MutationResult
    from provisa.cosmosdb.table import CosmosTableRefused
    from provisa.cosmosdb.table import check_table as check_cosmos_table
    from provisa.mongodb.native_query import NativeQueryRefused, check_table

    row = await source_row(conn, model.source_id)
    try:
        if row is not None and row["type"] == "cosmosdb":
            # REQ-1982: a container or a query table; its parameters are checked either way.
            check_cosmos_table(model)
        elif model.query_template and row is not None and row["type"] == "mongodb":
            check_table(model)
    except (NativeQueryRefused, CosmosTableRefused) as refused:
        return MutationResult(
            success=False, message=str(refused), code=refused.code, params=refused.params
        )
    return None


async def persist_query_api_registration(
    conn: "Connection", model: "Table"
) -> "MutationResult | None":
    """After the registered_tables row lands: refuse a query-API table with no query, else persist
    its endpoint and mirror it into the live endpoint map the schema builder and event loop read.
    No-op for every other source type."""
    from provisa.api.admin.types import MutationResult
    from provisa.api.app import state

    row = await source_row(conn, model.source_id)
    if row is None or row["type"] not in QUERY_API_TYPES:
        return None
    if not model.query_template:
        return MutationResult(
            success=False,
            message=f"A table on a {row['type']} source requires the query that produces its rows.",
            code="schema.query_template_required",
            params={"table": model.table_name, "source_type": row["type"]},
        )
    if row["type"] == "neo4j":
        from provisa.neo4j.persist import persist_neo4j_table

        api_source, endpoint = await persist_neo4j_table(
            conn,
            source_id=model.source_id,
            host=row["host"],
            port=row["port"],
            database=row["database"],
            base_url=None,
            table_name=model.table_name,
            query_template=model.query_template,
            columns=model.columns,
            ttl=model.cache_ttl or 300,
        )
    else:
        from provisa.sparql.persist import persist_sparql_table

        api_source, endpoint = await persist_sparql_table(
            conn,
            source_id=model.source_id,
            endpoint_url=row["host"],
            table_name=model.table_name,
            query_template=model.query_template,
            columns=model.columns,
            ttl=model.cache_ttl or 300,
        )
    if not isinstance(getattr(state, "api_sources", None), dict):
        state.api_sources = {}
    state.api_sources[api_source.id] = api_source
    from provisa.api_source.endpoints import put_endpoint

    put_endpoint(state, endpoint)
    return None
