# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A PostgreSQL source's change feed is its logical replication (REQ-929).

Against an embedded PostgreSQL run with ``wal_level=logical``: the database is refused by name
where it cannot give a slot; the slot reports which followed tables changed and nothing of the
others; the listener asks for a build of each changed table once per burst; and the slot and
its publication are dropped when no table follows them any more.
"""

# Requirements: REQ-929

from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

import psycopg
import pytest

from provisa.subscriptions import pg_logical
from tests.embedded_pg import DATABASE, PASSWORD, ROLE, start_local_postgres


@pytest.fixture(scope="module")
def logical_pg():
    pg = start_local_postgres(settings={"wal_level": "logical", "synchronous_commit": "on"})
    yield pg
    pg.stop()


@pytest.fixture
def conn(logical_pg):
    with psycopg.connect(logical_pg.dsn(), autocommit=True) as c:
        c.execute('DROP TABLE IF EXISTS orders, refunds, "Mixed ""Case"""')
        c.execute("CREATE TABLE orders (id integer PRIMARY KEY)")
        c.execute("CREATE TABLE refunds (id integer PRIMARY KEY)")
        c.execute('CREATE TABLE "Mixed ""Case""" (id integer PRIMARY KEY)')
        yield c
        for (slot,) in c.execute("SELECT slot_name FROM pg_replication_slots").fetchall():
            c.execute("SELECT pg_drop_replication_slot(%s)", (slot,))
        for (pub,) in c.execute("SELECT pubname FROM pg_publication").fetchall():
            c.execute(f'DROP PUBLICATION "{pub}"')


def _source(pg, source_id: str = "shop") -> SimpleNamespace:
    return SimpleNamespace(
        id=source_id,
        type="postgresql",
        host="127.0.0.1",
        port=pg.port,
        database=DATABASE,
        username=ROLE,
        password=PASSWORD,
    )


def test_a_database_that_cannot_give_a_slot_is_refused_by_name(logical_pg, conn):
    pg_logical.require(_source(logical_pg))  # the superuser on wal_level=logical: allowed
    conn.execute("DROP ROLE IF EXISTS reader")
    conn.execute("CREATE ROLE reader LOGIN PASSWORD 'reader'")
    reader = SimpleNamespace(
        **{**vars(_source(logical_pg)), "username": "reader", "password": "reader"}
    )
    with pytest.raises(
        pg_logical.LogicalReplicationRefused, match="no replication right"
    ) as refused:
        pg_logical.require(reader)
    assert refused.value.code == "schema.logical_replication_refused"
    assert refused.value.params["source"] == "shop"


def test_a_database_without_logical_wal_is_refused_by_name():
    plain = start_local_postgres()
    try:
        with pytest.raises(pg_logical.LogicalReplicationRefused, match="wal_level is 'replica'"):
            pg_logical.require(_source(plain))
    finally:
        plain.stop()


def test_the_slot_reports_the_followed_tables_that_changed(conn):
    name = pg_logical.slot_name("Shop-DB")
    assert name == "provisa_shop_db"
    pg_logical.ensure_slot(conn, name, [("public", "orders"), ("public", 'Mixed "Case"')])
    pg_logical.ensure_slot(conn, name, [("public", "orders"), ("public", 'Mixed "Case"')])
    conn.execute("INSERT INTO orders VALUES (1)")
    conn.execute('INSERT INTO "Mixed ""Case""" VALUES (1)')
    conn.execute("INSERT INTO refunds VALUES (1)")  # not followed
    assert pg_logical.read_changes(conn, name, 100) == {
        ("public", "orders"),
        ("public", 'Mixed "Case"'),
    }
    assert pg_logical.read_changes(conn, name, 100) == set()  # consumed
    conn.execute("TRUNCATE orders")
    conn.execute('DELETE FROM "Mixed ""Case"""')
    assert pg_logical.read_changes(conn, name, 100) == {
        ("public", "orders"),
        ("public", 'Mixed "Case"'),
    }


def test_following_another_set_of_tables_republishes_it(conn):
    name = pg_logical.slot_name("shop")
    pg_logical.ensure_slot(conn, name, [("public", "orders")])
    pg_logical.ensure_slot(conn, name, [("public", "refunds")])
    conn.execute("INSERT INTO orders VALUES (2)")
    conn.execute("INSERT INTO refunds VALUES (2)")
    assert pg_logical.read_changes(conn, name, 100) == {("public", "refunds")}


def test_dropping_the_slot_drops_its_publication_too(conn):
    name = pg_logical.slot_name("shop")
    pg_logical.ensure_slot(conn, name, [("public", "orders")])
    pg_logical.drop_slot(conn, name)
    pg_logical.drop_slot(conn, name)  # nothing left to drop: no error
    held = conn.execute(
        "SELECT (SELECT count(*) FROM pg_replication_slots), (SELECT count(*) FROM pg_publication)"
    ).fetchone()
    assert held == (0, 0)


def test_the_listener_asks_for_a_build_of_each_changed_table(logical_pg, conn, monkeypatch):
    """The slot is opened with a build of every followed table (what changed before is unknown);
    then each burst asks once for each table it touched, and for no other."""
    from provisa.events import push_wiring
    from provisa.federation import replica_builds

    asked: list[int] = []

    async def _request(state, table_id, source_id, reason):
        asked.append(table_id)
        return True

    monkeypatch.setattr(replica_builds, "request_if_replicated", _request)
    monkeypatch.setattr(push_wiring, "_LOGICAL_POLL_SECONDS", 0.05)
    disconnect = threading.Event()
    state = SimpleNamespace(active_org_id="default")

    async def _scenario() -> None:
        listener = asyncio.create_task(
            push_wiring._run_logical_stream(
                state=state,
                source=_source(logical_pg),
                followed=[("public", "orders", 1), ("public", "refunds", 2)],
                disconnect=disconnect,
                log=logging.getLogger("test"),
            )
        )
        while sorted(asked) != [1, 2]:
            await asyncio.sleep(0.05)
        asked.clear()
        conn.execute("INSERT INTO orders VALUES (3)")
        conn.execute("INSERT INTO orders VALUES (4)")
        for _ in range(100):
            if asked:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)  # the burst asked once, and only for orders
        disconnect.set()
        await asyncio.wait_for(listener, 5)

    asyncio.run(_scenario())
    assert asked == [1]


def test_a_source_whose_tables_stop_following_it_has_its_slot_dropped(logical_pg, conn):
    from provisa.events import push_wiring

    name = pg_logical.slot_name("shop")
    pg_logical.ensure_slot(conn, name, [("public", "orders")])
    state = SimpleNamespace(
        active_org_id="default", logical_slot_sources={"shop": _source(logical_pg)}
    )
    asyncio.run(push_wiring._drop_unfollowed_slots(state, {}, log=logging.getLogger("test")))
    assert conn.execute("SELECT count(*) FROM pg_replication_slots").fetchone() == (0,)
    assert state.logical_slot_sources == {}
