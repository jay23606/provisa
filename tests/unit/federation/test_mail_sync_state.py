# Copyright (c) 2026 Kenneth Stott
# Canary: 31577376-c354-445d-8eb8-1feb9f598231
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Where the last completed read of a mail source reached (REQ-1923): one token for each
(source, mailbox, scope, kind), kept in the org's state store and gone with its source."""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from provisa.core import env_classes, store_sides
from provisa.core.database import Database, create_engine_from_url
from provisa.core.db import _init_schema_portable
from provisa.core.schema_org import mail_sync_state as table
from provisa.core.schema_org import sources
from provisa.federation import mail_sync_state as kept

pytestmark = pytest.mark.unit

A, B = "megan@contoso.com", "sam@contoso.com"


@pytest.fixture
async def db():
    made = Database(create_engine_from_url("sqlite+pysqlite:///:memory:"), name="mail-sync")
    await _init_schema_portable(made)
    yield made
    await made.close()


async def test_what_a_read_reached_replaces_what_was_kept_for_the_source(db):
    link = "https://graph.microsoft.com/v1.0/users/x/mailFolders/f/messages/delta?$deltatoken=" + (
        "t" * 4000
    )
    async with db.acquire() as conn:
        assert await kept.read_all(conn, "mail") == {}
        await kept.replace(
            conn,
            "mail",
            {(A, "f1", kept.DELTA): link, (A, "", kept.DELTA): "l0", (B, "", kept.PROBE): "h7"},
        )
        await kept.replace(conn, "other", {(A, "", kept.PROBE): "h1"})
        assert await kept.read_all(conn, "mail") == {
            (A, "f1", kept.DELTA): link,  # a link is long, and kept whole
            (A, "", kept.DELTA): "l0",
            (B, "", kept.PROBE): "h7",
        }
        # The next completed read no longer saw mailbox B, nor folder f1 of A.
        await kept.replace(conn, "mail", {(A, "f2", kept.DELTA): "l2", (A, "", kept.DELTA): "l9"})
        assert await kept.read_all(conn, "mail") == {
            (A, "f2", kept.DELTA): "l2",
            (A, "", kept.DELTA): "l9",
        }
        assert await kept.read_all(conn, "other") == {(A, "", kept.PROBE): "h1"}
        await kept.forget(conn, "mail")
        assert await kept.read_all(conn, "mail") == {}


async def test_a_kind_of_token_nobody_reads_is_refused_and_nothing_is_changed(db):
    async with db.acquire() as conn:
        await kept.replace(conn, "mail", {(A, "", kept.DELTA): "l0"})
        with pytest.raises(ValueError, match="no such kind of token: cursor"):
            await kept.replace(conn, "mail", {(A, "", "cursor"): "x"})
        assert await kept.read_all(conn, "mail") == {(A, "", kept.DELTA): "l0"}


async def test_what_was_kept_goes_with_its_source(db):
    from provisa.core.repositories import source as source_repo

    async with db.acquire() as conn:
        await conn.execute_core(insert(sources).values(id="mail", type="microsoft_365"))
        await kept.replace(conn, "mail", {(A, "", kept.DELTA): "l0"})
        assert await source_repo.delete(conn, "mail") is True
        rows = (await conn.execute_core(select(table.c.source_id))).fetchall()
        assert rows == []


def test_it_is_state_of_one_environment_and_region_not_part_of_the_model():
    assert "mail_sync_state" in store_sides.STATE
    assert "mail_sync_state" in env_classes.NEVER_RUNTIME
    assert "mail_sync_state" not in env_classes.CARRIED


async def test_every_table_a_source_is_building_says_what_its_read_is_waiting_out(db):
    """One read feeds every table of the source it builds: while its service is throttling
    it, each running build says so, and stops saying so when the wait is over or it ends."""
    from datetime import UTC, datetime

    from provisa.federation import replica_state
    from provisa.federation.replica_state import RetryPolicy

    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    building = [("mail", "default", "messages"), ("mail", "default", "threads")]
    idle = ("mail", "default", "folders")
    other = ("crm", "public", "accounts")
    async with db.acquire() as conn:
        for key in (*building, idle, other):
            await replica_state.request_build(conn, key, replica_state.REASON_MODEL)
        for key in (*building, other):
            await replica_state.claim(conn, key, holder="h:1", now=now, retry=RetryPolicy(60, 3600))
        await replica_state.record_throttled(conn, "mail", seconds=87, by="Microsoft", now=now)
        for key in building:
            assert (await replica_state.read(conn, key)).build_wait == {
                "by": "Microsoft",
                "seconds": 87,
                "until": "2026-10-10T12:01:27+00:00",
            }
        assert (await replica_state.read(conn, idle)).build_wait is None  # not being built
        assert (await replica_state.read(conn, other)).build_wait is None  # another source's
        await replica_state.record_throttled(conn, "mail", seconds=0, by="Microsoft", now=now)
        assert (await replica_state.read(conn, building[0])).build_wait is None
        await replica_state.record_throttled(conn, "mail", seconds=30, by="Microsoft", now=now)
        await replica_state.record_failed(conn, building[1], error="stopped", now=now)
        assert (await replica_state.read(conn, building[1])).build_wait is None
