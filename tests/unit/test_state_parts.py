# Copyright (c) 2026 Kenneth Stott
# Canary: 2cb27c99-4c18-4484-91b8-4dd03a887ad3
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An object of the model can have parts kept in a region's state store (REQ-1922): a table's file
mtimes, an MV's refresh log and delta ledger. Removing the object removes them in the region that
removed it; every other region removes its own when it prunes."""

# Requirements: REQ-1922

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, insert, select

from provisa.core import request_context
from provisa.core.database import Database
from provisa.core.db import init_schema
from provisa.core.environments import org_schema
from provisa.core.repositories.integrity import ObjectRef, discard, prune_state_parts
from tests.pg_control_plane import SCHEMA_SQL
from provisa.core.schema_org import (
    domains,
    file_source_mtimes,
    materialized_views,
    mv_delta_ledger,
    mv_refresh_log,
    registered_tables,
    sources,
)

_STATE_PARTS = (file_source_mtimes, mv_refresh_log, mv_delta_ledger)


def _store(control_plane, org_id: str, holds: str) -> Database:
    """A store of its own: the org schema ``org_id`` laid out whole, held on one side."""
    db = control_plane.org(org_id, holds=holds)
    if org_id != "default":
        asyncio.run(init_schema(db, SCHEMA_SQL, org_id=org_id))
    return db


@pytest.fixture
def stores(control_plane, monkeypatch):
    """The org's model store and the state stores of two of its regions: three databases."""
    model_db = _store(control_plane, "default", "model")
    here = _store(control_plane, "eu", "state")
    there = _store(control_plane, "us", "state")
    sides = {"model": model_db, "state": here}
    monkeypatch.setattr(request_context, "_org_store_provider", lambda side: sides[side])
    return model_db, here, there


async def _seed(model_db: Database, *state_dbs: Database) -> int:
    async with model_db.acquire() as conn:
        await conn.execute_core(insert(sources).values(id="files", type="csv"))
        await conn.execute_core(insert(domains).values(id="sales"))
        result = await conn.execute_core(
            insert(registered_tables).values(
                source_id="files",
                domain_id="sales",
                schema_name="public",
                table_name="orders",
            )
        )
        table_id = result.inserted_primary_key[0]
        await conn.execute_core(
            insert(materialized_views).values(
                id="mv_orders",
                source_tables=["orders"],
                target_catalog="store",
                target_schema="mv_cache",
                target_table="mv_orders",
            )
        )
    for state_db in state_dbs:
        async with state_db.acquire() as conn:
            await conn.execute_core(
                insert(file_source_mtimes).values(table_id=table_id, source_mtime=1, synced_at=1)
            )
            await conn.execute_core(
                insert(mv_refresh_log).values(mv_id="mv_orders", status="success")
            )
            await conn.execute_core(
                insert(mv_delta_ledger).values(
                    mv_id="mv_orders",
                    refresh_version=1,
                    definition_version="d1",
                    change_type="insert",
                    row_key="1",
                )
            )
    return table_id


async def _counts(state_db: Database) -> list[int]:
    async with state_db.acquire() as conn:
        return [
            (await conn.execute_core(select(func.count()).select_from(t))).scalar_one()
            for t in _STATE_PARTS
        ]


async def test_removing_a_table_and_a_view_removes_their_state_rows_in_this_region(stores):
    model_db, here, _ = stores
    table_id = await _seed(model_db, here)
    assert await _counts(here) == [1, 1, 1]
    async with model_db.acquire() as conn:
        await discard(conn, ObjectRef("table", table_id))
        await discard(conn, ObjectRef("materialized_view", "mv_orders"))
    assert await _counts(here) == [0, 0, 0]


async def test_another_region_removes_its_own_when_it_prunes(stores):
    model_db, here, there = stores
    table_id = await _seed(model_db, here, there)
    async with model_db.acquire() as conn:
        await discard(conn, ObjectRef("table", table_id))
        await discard(conn, ObjectRef("materialized_view", "mv_orders"))
    assert await _counts(there) == [1, 1, 1]  # the other region's store is not this node's
    removed = await prune_state_parts(model_db, there)
    assert removed == {
        "file_source_mtimes.table_id": 1,
        "mv_refresh_log.mv_id": 1,
        "mv_delta_ledger.mv_id": 1,
    }
    assert await _counts(there) == [0, 0, 0]
    assert await prune_state_parts(model_db, there) == {}


async def test_a_prune_keeps_the_rows_of_objects_the_model_still_has(stores):
    model_db, here, _ = stores
    await _seed(model_db, here)
    assert await prune_state_parts(model_db, here) == {}
    assert await _counts(here) == [1, 1, 1]


async def test_with_one_database_keeping_every_side_a_table_is_removed_in_one_transaction(
    control_plane, monkeypatch
):
    """The implicit region keeps its state with the model, in the control plane's one database
    (region_stores.open_org_stores): both handles are over one engine. Removing a table in a
    transaction reached its state part through a SECOND connection to that database, which
    waited on the first's write lock and the table stayed."""
    engine = control_plane.engine()
    schema = org_schema("default")
    model_db = Database(engine, "org-model", search_path=schema, holds="model")
    state_db = Database(engine, "org-state", search_path=schema, holds="state")
    sides = {"model": model_db, "state": state_db}
    monkeypatch.setattr(request_context, "_org_store_provider", lambda side: sides[side])
    table_id = await _seed(model_db, state_db)
    async with model_db.acquire() as conn:
        async with conn.transaction():
            await discard(conn, ObjectRef("table", table_id))
    assert (await _counts(state_db))[0] == 0
    async with model_db.acquire() as conn:
        left = await conn.execute_core(select(func.count()).select_from(registered_tables))
        assert left.scalar_one() == 0
