# Copyright (c) 2026 Kenneth Stott
# Canary: 5f2a9c14-7e3b-4d68-9a05-1c8f6e2b7d91
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1008: list_schemas/list_tables/search_catalog against a REAL async DB, unmocked.

Regression coverage for a real bug: `_catalog()` used to call the sync `build_catalog_tables`
wrapper via `asyncio.to_thread`, which spins up a brand-new event loop and tries to use
`state.tenant_db`'s pool — bound to the CALLER's event loop — from within it. Async DB drivers
reject that cross-event-loop reuse. Every MCP tool that reached `_catalog()` failed, but the
existing test suite only ever exercised it with `_build_catalog_tables_async` monkeypatched away
entirely (test_mcp_server.py), so the real DB path was never actually run. This file runs it for
real, on a genuine PostgreSQL-backed Database, with no catalog mock."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import insert

from provisa.core.models import Column, Table
from provisa.core.repositories import table as table_repo
from provisa.core.schema_org import domains, registered_tables, sources
from tests.role_state import RoleState

pytestmark = pytest.mark.asyncio


async def _seeded_db(control_plane):
    with control_plane.engine().begin() as c:
        c.exec_driver_sql('SET LOCAL search_path TO "org_default"')
        c.execute(insert(domains).values(id="sales", description=""))
        c.execute(insert(sources).values(id="__derived__", type="postgresql"))
    db = control_plane.org()
    async with db.acquire() as conn:
        await table_repo.upsert(
            conn,
            Table(
                source_id="__derived__",
                domain_id="sales",
                schema_name="public",
                table_name="orders",
                columns=[Column(name="id", data_type="integer", visible_to=["analyst"])],
                view_sql="SELECT 1 AS id",
            ),
        )
    return db


def _state(db):
    # The analyst's compiled context, as a schema build leaves it for the table seeded above:
    # the tools list what the role is served, so a context with no table is an empty catalog.
    from provisa.compiler.sql_types import TableMeta

    with db._engine.begin() as c:
        c.exec_driver_sql('SET LOCAL search_path TO "org_default"')
        (table_id,) = c.execute(
            registered_tables.select().with_only_columns(registered_tables.c.id)
        ).one()
    orders = TableMeta(
        table_id=table_id,
        field_name="orders",
        type_name="Orders",
        source_id="__derived__",
        catalog_name="derived",
        schema_name="public",
        table_name="orders",
        domain_id="sales",
    )
    return RoleState(
        contexts={
            "analyst": types.SimpleNamespace(
                tables={"orders": orders}, joins={}, physical_to_sql={(table_id, "id"): "id"}
            )
        },
        roles={"analyst": {"domain_access": ["*"]}},
        config=types.SimpleNamespace(domains=[]),
        model_db=db,
        tenant_db=db,
        engine_conn=None,
    )


async def test_list_schemas_against_real_db_no_event_loop_error(control_plane):
    from provisa.api.mcp import tools

    db = await _seeded_db(control_plane)
    result = await tools.list_schemas(_state(db), "analyst")
    assert result == [{"schema": "sales", "description": "", "table_count": 1}]


async def test_list_tables_against_real_db_no_event_loop_error(control_plane):
    from provisa.api.mcp import tools

    db = await _seeded_db(control_plane)
    result = await tools.list_tables(_state(db), "analyst", "sales")
    assert [r["table"] for r in result] == ["orders"]


async def test_catalog_returns_empty_list_when_no_tenant_db():
    from provisa.api.mcp import tools

    state = types.SimpleNamespace(model_db=None, tenant_db=None)
    assert await tools._catalog(state, None) == []
