# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A live ServiceNow source end to end (REQ-1954): created and its tables registered through the
admin GraphQL, read through the settled pipeline with a filter and a limit, and written through
GraphQL mutations on both write routes:

- ``incident``, bound to no import set: its insert, update and delete are written to the table;
- ``sys_user``, bound to the import set of one of the instance's transform maps into it: its
  insert goes through the instance's Import Set API; its delete is written to the table.

The DuckDB engine reads the source by attaching its own server; see ``test_servicenow_source_e2e``
for the server alone. It reads SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME and
SERVICENOW_PASSWORD. Every record it writes is named ``provisa-itest-`` plus a random suffix and is
deleted by that name whether the test passes or fails; it touches no record it did not create. The
staging rows the import set keeps are the instance's own record of the insert.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.integration.connector_source_harness import (
    _gql,
    create_domain,
    query_semantic,
    rebuild_schemas,
)
from tests.helpers import registered_id, release_mutation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_servicenow,
    pytest.mark.requires_warehouse,
    pytest.mark.asyncio(loop_scope="session"),
]

_SOURCE_ID = "servicenow-pipeline"
_SCHEMA = "servicenow_pipeline"
_DOMAIN = "snow_e2e"
_ROLE = "org_admin"
_VISIBLE_TO = '["org_admin"]'


@pytest_asyncio.fixture(loop_scope="session", scope="module")
async def client():
    """An in-process app on the DuckDB engine, which attaches the source's own server."""
    import provisa.api.app as app_mod
    from provisa.federation.engine import build_engine
    from provisa.federation.runtime import EngineRuntime

    prior_env = os.environ.get("PROVISA_ENGINE")
    os.environ["PROVISA_ENGINE"] = "duckdb"
    prior_engine = app_mod.state.federation_engine
    app_mod.state.federation_engine = EngineRuntime(build_engine(), app_mod.state)
    app_mod.state.federation_engine.bind_terminal()
    try:
        app = app_mod.create_app()
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as c:
                yield c
    finally:
        app_mod.state.federation_engine = prior_engine
        if prior_env is None:
            os.environ.pop("PROVISA_ENGINE", None)
        else:
            os.environ["PROVISA_ENGINE"] = prior_env


async def _admin(client: AsyncClient, query: str) -> dict[str, Any]:
    resp = await client.post("/admin/graphql", json={"query": query})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "errors" not in body, resp.text
    return body["data"]


async def _data(client: AsyncClient, query: str) -> dict[str, Any]:
    resp = await client.post(
        "/data/graphql", json={"query": query}, headers={"x-provisa-role": _ROLE}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "errors" not in body, resp.text
    return body["data"]


async def _register(
    client: AsyncClient, table: str, columns: list[str], import_set: str | None = None
) -> None:
    cols = ", ".join(f'{{ name: "{c}", visibleTo: {_VISIBLE_TO} }}' for c in columns)
    bound = f", importSet: {json.dumps(import_set)}" if import_set else ""
    registered = await _gql(
        client,
        f"""
        mutation {{
            registerTable(input: {{
                sourceId: "{_SOURCE_ID}", domainId: "{_DOMAIN}", schemaName: "{_SCHEMA}",
                tableName: "{table}", alias: "{table}", columns: [{cols}]{bound}
            }}) {{ success message }}
        }}
        """,
        "registerTable",
    )
    await _gql(client, release_mutation(registered_id(registered["message"])), "setTableDraft")


async def _mutation(client: AsyncClient, verb: str, table: str) -> str:
    """The data GraphQL mutation field that ``verb``s ``table`` (insertIncident, updateSysUser...)."""
    data = await _data(client, "{ __schema { mutationType { fields { name } } } }")
    names = [f["name"] for f in data["__schema"]["mutationType"]["fields"]]
    wanted = verb + "".join(part.capitalize() for part in table.split("_"))
    (field,) = [n for n in names if n.split("__")[-1] == wanted]
    return field


@pytest_asyncio.fixture(loop_scope="session", scope="module")
async def registered(client):
    """The source, ``incident`` unbound and ``sys_user`` bound to an import set, released and in
    the schema; the import set is the first of the instance's transform maps into sys_user."""
    await create_domain(client, _DOMAIN)
    await _gql(
        client,
        f"""
        mutation {{
            createSource(input: {{
                id: "{_SOURCE_ID}", type: "servicenow",
                host: {json.dumps(os.environ["SERVICENOW_INSTANCE_URL"])}, port: 0, database: "",
                username: {json.dumps(os.environ["SERVICENOW_USERNAME"])},
                password: {json.dumps(os.environ["SERVICENOW_PASSWORD"])}
            }}) {{ success message }}
        }}
        """,
        "createSource",
    )
    maps = (
        await _admin(
            client,
            f'{{ availableImportSets(sourceId: "{_SOURCE_ID}", schemaName: "{_SCHEMA}", '
            'tableName: "sys_user") { name importSet } }',
        )
    )["availableImportSets"]
    assert maps, "the instance has no active transform map into sys_user"
    import_set = maps[0]["importSet"]
    await _register(client, "incident", ["sys_id", "number", "short_description", "active"])
    await _register(client, "sys_user", ["sys_id", "user_name", "first_name"], import_set)
    await rebuild_schemas(client)
    return import_set


def _own_name() -> str:
    return f"provisa-itest-{uuid.uuid4().hex[:12]}"


async def test_a_registered_table_is_read_through_a_filter_and_a_limit(client, registered):
    del registered
    rows = await query_semantic(
        client,
        f'SELECT "number", "active" FROM "{_DOMAIN}"."incident" WHERE "active" = TRUE LIMIT 5',
    )
    assert 0 < len(rows) <= 5
    assert all(r["number"].startswith("INC") and r["active"] for r in rows)


async def _incidents_named(client: AsyncClient, name: str) -> list[dict[str, Any]]:
    return await query_semantic(
        client,
        f'SELECT "sys_id", "short_description" FROM "{_DOMAIN}"."incident" '
        f"WHERE \"short_description\" LIKE '{name}%'",
    )


async def test_an_unbound_tables_insert_update_and_delete_are_written_to_it(client, registered):
    del registered
    name = _own_name()
    insert = await _mutation(client, "insert", "incident")
    update = await _mutation(client, "update", "incident")
    delete = await _mutation(client, "delete", "incident")
    try:
        written = await _data(
            client,
            f'mutation {{ {insert}(input: {{short_description: "{name}"}}) '
            "{ affected_rows returning { sys_id short_description } } }",
        )
        assert written[insert]["affected_rows"] == 1
        assert written[insert]["returning"][0]["short_description"] == name
        await _data(
            client,
            f'mutation {{ {update}(where: {{short_description: {{eq: "{name}"}}}}, '
            f'set: {{short_description: "{name} changed"}}) {{ affected_rows }} }}',
        )
        assert [r["short_description"] for r in await _incidents_named(client, name)] == [
            f"{name} changed"
        ]
    finally:
        await _data(
            client,
            f'mutation {{ {delete}(where: {{short_description: {{like: "{name}%"}}}}) '
            "{ affected_rows } }",
        )
    assert await _incidents_named(client, name) == []


async def test_a_bound_tables_insert_goes_through_its_import_set(client, registered):
    del registered
    name = _own_name()
    insert = await _mutation(client, "insert", "sys_user")
    delete = await _mutation(client, "delete", "sys_user")
    try:
        written = await _data(
            client,
            f'mutation {{ {insert}(input: {{user_name: "{name}", first_name: "Provisa"}}) '
            "{ affected_rows returning { sys_id user_name } } }",
        )
        # The returned row is the record the transform wrote into sys_user.
        assert written[insert]["returning"][0]["user_name"] == name
        assert written[insert]["returning"][0]["sys_id"]
    finally:
        await _data(
            client,
            f'mutation {{ {delete}(where: {{user_name: {{eq: "{name}"}}}}) {{ affected_rows }} }}',
        )
    rows = await query_semantic(
        client, f'SELECT "sys_id" FROM "{_DOMAIN}"."sys_user" WHERE "user_name" = \'{name}\''
    )
    assert rows == []
