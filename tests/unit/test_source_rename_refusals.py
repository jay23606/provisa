# Copyright (c) 2026 Kenneth Stott
# Canary: 9b1f4c27-5e83-4a06-8d2c-1e7a3f9b6c50
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A source rename onto another source's id is refused by name before anything is written: it
used to move the renamed source's tables into the other source and delete the renamed one. A
rename onto its own id changes nothing: it used to delete the source (REQ-012)."""

# Requirements: REQ-012

from __future__ import annotations

import types
from typing import Any

import pytest
from sqlalchemy import insert, select

from provisa.api.admin import schema_mutation
from provisa.core.database import Database
from provisa.core.repositories import source as source_repo
from provisa.core.schema_org import domains, registered_tables, sources


@pytest.fixture
async def plane(monkeypatch, control_plane) -> Database:
    """Two sources, each with a table."""
    db = control_plane.org()
    async with db.acquire() as conn:
        await conn.execute_core(insert(domains).values(id="sales"))
        for source_id, host in (("crm", "crm.example.com"), ("erp", "erp.example.com")):
            await conn.execute_core(
                insert(sources).values(id=source_id, type="postgresql", host=host)
            )
            await conn.execute_core(
                insert(registered_tables).values(
                    source_id=source_id,
                    domain_id="sales",
                    schema_name="public",
                    table_name=f"{source_id}_accounts",
                )
            )

    async def _pool():
        return db

    monkeypatch.setattr(schema_mutation, "_get_pool", _pool)
    monkeypatch.setattr(schema_mutation, "require_capability", lambda _info, _cap: None)
    return db


async def _stored(db: Database) -> tuple[list[tuple], list[tuple]]:
    async with db.acquire() as conn:
        srcs = (
            await conn.execute_core(select(sources.c.id, sources.c.host).order_by(sources.c.id))
        ).fetchall()
        tables = (
            await conn.execute_core(
                select(registered_tables.c.table_name, registered_tables.c.source_id).order_by(
                    registered_tables.c.table_name
                )
            )
        ).fetchall()
    return [tuple(r) for r in srcs], [tuple(r) for r in tables]


async def _rename(old_id: str, new_id: str):
    info: Any = types.SimpleNamespace(context={})
    mutation: Any = schema_mutation.Mutation()
    return await mutation.rename_source(info, old_id, new_id)


async def test_a_rename_onto_another_sources_id_is_refused_and_writes_nothing(plane):
    before = await _stored(plane)
    result = await _rename("crm", "erp")
    assert (result.success, result.code, result.params) == (
        False,
        "schema.source_id_taken",
        {"source": "erp"},
    )
    assert await _stored(plane) == before


async def test_a_rename_onto_its_own_id_changes_nothing(plane):
    before = await _stored(plane)
    result = await _rename("crm", "crm")
    assert (result.success, result.code) == (True, "schema.source_renamed")
    assert await _stored(plane) == before


async def test_a_rename_onto_a_free_id_moves_the_source_and_its_tables(plane):
    result = await _rename("crm", "sales_crm")
    assert (result.success, result.code) == (True, "schema.source_renamed")
    assert await _stored(plane) == (
        [("erp", "erp.example.com"), ("sales_crm", "crm.example.com")],
        [("crm_accounts", "sales_crm"), ("erp_accounts", "erp")],
    )


async def test_the_repository_refuses_by_name(plane):
    async with plane.acquire() as conn:
        with pytest.raises(source_repo.SourceIdTaken, match="'erp' already exists"):
            await source_repo.rename(conn, "crm", "erp")
