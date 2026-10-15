# Copyright (c) 2026 Kenneth Stott
# Canary: 5ccd52a5-648f-4441-bbbf-1cd0256e68e9
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1926: a session's temporary tables are bounded, and the schema a session that is gone left
in the store is dropped by any worker's keeper.

The schema a session holds its tables in is recorded in its org environment's state before its
first table is written; the worker holding the session renews it, and a keeper drops a schema
whose session has said nothing for longer than GONE_AFTER."""

# Requirements: REQ-1926

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from provisa.compiler.temp_tables import TempSession, TempTable
from provisa.core.schema_org import session_temp_schemas
from provisa.pgwire import temp_exec, temp_keeper


def _state(db):
    return SimpleNamespace(
        tenant_db=db,
        federation_engine=SimpleNamespace(
            engine=SimpleNamespace(materialize_store=lambda: "store-dsn")
        ),
        org_registry=SimpleNamespace(
            runtimes=lambda: [SimpleNamespace(org_id="default", env=None)]
        ),
    )


async def _recorded(db) -> dict[str, tuple[str, datetime]]:
    async with db.acquire() as conn:
        rows = (await conn.execute_core(select(session_temp_schemas))).fetchall()
    return {r.store_schema: (r.session_id, r.beat_at) for r in rows}


@pytest.fixture
def state_db(control_plane):
    """The org's STATE handle, as the server binds tenant_db: it refuses a model table by name,
    so a sweep that read the record through the wrong handle fails here as it did live."""
    from provisa.core.database import Database
    from provisa.core.environments import org_schema

    return Database(
        control_plane.engine(), "state", search_path=org_schema("default"), holds="state"
    )


@pytest.fixture
def dropped(monkeypatch):
    dropped: list[str] = []

    async def drop(dsn: str, schema: str) -> None:
        assert dsn == "store-dsn"
        dropped.append(schema)

    monkeypatch.setattr("provisa.federation.store_scope.drop_temp_schema", drop)
    monkeypatch.setattr(temp_keeper, "_live", {})
    return dropped


async def test_a_sessions_schema_is_recorded_renewed_and_forgotten(state_db, dropped):
    db = state_db
    state = _state(db)
    session = TempSession()
    await temp_keeper.note_stored(state, session, "org_default_replicas__tmp_a")
    ((sid, first),) = (await _recorded(db)).values()
    assert sid == session.id

    later = first + timedelta(minutes=2)
    assert await temp_keeper.beat(state, later) == 1
    assert (await _recorded(db))["org_default_replicas__tmp_a"][1] == later

    await temp_keeper.note_ended(state, session, "org_default_replicas__tmp_a")
    assert await _recorded(db) == {}
    assert await temp_keeper.beat(state, later) == 0


async def test_a_gone_sessions_schema_is_dropped_and_a_live_ones_kept(state_db, dropped):
    db = state_db
    state = _state(db)
    live, gone = TempSession(), TempSession()
    await temp_keeper.note_stored(state, live, "org_default_replicas__tmp_live")
    await temp_keeper.note_stored(state, gone, "org_default_replicas__tmp_gone")
    temp_keeper._live.pop(gone.id)  # its worker is gone: nothing renews it

    now = datetime.now(UTC) + temp_keeper.GONE_AFTER + timedelta(seconds=1)
    await temp_keeper.beat(state, now)
    assert await temp_keeper.reap(state, now) == ["org_default_replicas__tmp_gone"]
    assert dropped == ["org_default_replicas__tmp_gone"]
    assert set(await _recorded(db)) == {"org_default_replicas__tmp_live"}


def test_a_table_past_the_sessions_limit_is_refused_by_name(monkeypatch):
    from provisa.core import settings_registry

    monkeypatch.setattr(
        settings_registry, "value", lambda key: {"temp_tables.max_per_session": 2}[key]
    )
    session = TempSession(tables={"a": TempTable("a", []), "b": TempTable("b", [])})
    with pytest.raises(ValueError, match=r"'c'.*holds 2 temporary.*max_per_session = 2"):
        temp_exec._within_tables(session, "c")
    temp_exec._within_tables(TempSession(tables={"a": TempTable("a", [])}), "c")


def test_a_table_past_the_row_limit_is_refused_not_cut(monkeypatch):
    from provisa.core import settings_registry

    monkeypatch.setattr(settings_registry, "value", lambda key: {"temp_tables.max_rows": 10}[key])
    temp_exec._within_rows("t", 10)
    with pytest.raises(ValueError, match=r"'t' would hold 11 rows.*max_rows = 10"):
        temp_exec._within_rows("t", 11)
