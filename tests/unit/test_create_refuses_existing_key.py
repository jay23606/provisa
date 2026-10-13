# Copyright (c) 2026 Kenneth Stott
# Canary: 8f3b6d27-1e94-4c58-a0b7-3d9e2c6f5a81
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A create makes a new object: a key that exists is refused by name before anything is written,
and the store is unchanged. A create used to overwrite the object holding the key and report it
created; changing an object is its update."""

# Requirements: REQ-021

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import insert, select

from provisa.api.admin import schema_mutation
from provisa.api.admin.types import DomainInput
from provisa.core.database import Database, create_engine_from_url
from provisa.core.db import _init_schema_portable
from provisa.core.schema_org import domains

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def plane(monkeypatch) -> Database:
    db = Database(create_engine_from_url("sqlite+pysqlite:///:memory:"), name="create-taken")
    await _init_schema_portable(db)
    async with db.acquire() as conn:
        await conn.execute_core(
            insert(domains).values(id="sales", description="The sales team's data")
        )

    async def _pool():
        return db

    monkeypatch.setattr(schema_mutation, "_get_pool", _pool)
    from provisa.api.admin import capabilities

    monkeypatch.setattr(capabilities, "require_capability", lambda _info, _cap: None)
    return db


async def _rows(db: Database, table) -> list[tuple]:
    async with db.acquire() as conn:
        return [tuple(r) for r in (await conn.execute_core(select(table))).fetchall()]


async def test_a_domain_create_on_an_existing_id_is_refused_and_writes_nothing(plane):
    before = await _rows(plane, domains)
    mutation: Any = schema_mutation.Mutation()
    result = await mutation.create_domain(None, DomainInput(id="sales", description="overwritten"))
    assert (result.success, result.code, result.params) == (
        False,
        "schema.domain_id_taken",
        {"domain": "sales"},
    )
    assert await _rows(plane, domains) == before


async def test_a_domain_create_on_a_new_id_creates_it(plane):
    mutation: Any = schema_mutation.Mutation()
    result = await mutation.create_domain(None, DomainInput(id="finance", description="Money"))
    assert (result.success, result.code) == (True, "schema.domain_created")
    assert {"sales", "finance"} <= {r[0] for r in await _rows(plane, domains)}
