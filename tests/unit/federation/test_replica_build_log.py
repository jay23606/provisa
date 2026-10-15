# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1915: every replica build that ends -- completed or failed -- is appended to the build log
as its record is written, with when it started; each replica keeps its last
REPLICA_BUILD_LOG_KEEP builds, and a replica that is forgotten takes its builds with it. The ops
views read the log and the records: what the admin Reports page shows."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from provisa.core.schema_org import replica_build_log
from provisa.federation import replica_state as build_state
from provisa.federation.replica_state import RetryPolicy

KEY = ("src", "public", "orders")
OTHER = ("src", "public", "customers")
T0 = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


@pytest.fixture
async def conn(control_plane):
    async with control_plane.org().acquire() as connection:
        yield connection


async def _build(conn, key, at, *, fail: str | None = None, code: str | None = None):
    await build_state.request_build(conn, key, build_state.REASON_MODEL)
    await build_state.claim(conn, key, holder="h:1", retry=RetryPolicy(0, 0), now=at)
    done = at + timedelta(seconds=30)
    if fail is not None:
        await build_state.record_failed(conn, key, error=fail, code=code, now=done)
    else:
        await build_state.record_completed(
            conn,
            key,
            rows_copied=100,
            method="stream_batches",
            content_hash="h",
            store="store-a",
            next_refresh_at=None,
            now=done,
        )


async def _log(conn, key=KEY):
    c = replica_build_log.c
    return (
        await conn.execute_core(
            select(
                c.started_at,
                c.finished_at,
                c.outcome,
                c.method,
                c.rows_copied,
                c.error_code,
                c.error_message,
            )
            .where(c.source_id == key[0], c.schema_name == key[1], c.table_name == key[2])
            .order_by(c.id)
        )
    ).fetchall()


async def test_a_completed_build_is_logged_with_its_start_rows_and_method(conn):
    await _build(conn, KEY, T0)
    (row,) = await _log(conn)
    assert tuple(row) == (
        T0,
        T0 + timedelta(seconds=30),
        "completed",
        "stream_batches",
        100,
        None,
        None,
    )


async def test_a_failed_build_is_logged_with_its_error_and_code(conn):
    await _build(conn, KEY, T0, fail="the source refused", code="replica.source_refused")
    (row,) = await _log(conn)
    assert tuple(row) == (
        T0,
        T0 + timedelta(seconds=30),
        "failed",
        None,
        None,
        "replica.source_refused",
        "the source refused",
    )
    # The record says the same as the log.
    record = await build_state.read(conn, KEY)
    assert (record.build_state, record.last_error) == ("failed", "the source refused")


async def test_each_replica_keeps_its_last_builds_only(conn, monkeypatch):
    monkeypatch.setattr(build_state, "REPLICA_BUILD_LOG_KEEP", 3)
    for n in range(5):
        await _build(conn, KEY, T0 + timedelta(minutes=n), fail="x" if n % 2 else None)
    await _build(conn, OTHER, T0)
    kept = await _log(conn)
    assert [r.started_at for r in kept] == [T0 + timedelta(minutes=n) for n in (2, 3, 4)]
    assert len(await _log(conn, OTHER)) == 1  # another replica's history is its own


async def test_a_forgotten_replica_takes_its_builds_with_it(conn):
    await _build(conn, KEY, T0)
    await build_state.retire(conn, KEY, now=T0 + timedelta(hours=1))
    assert await build_state.forget(conn, KEY)
    assert await _log(conn) == []


async def test_the_ops_views_read_the_records_and_the_log(conn):
    from provisa.api._meta_views import _OPS_LOG_TABLE_VIEWS, _OPS_REPORT_VIEWS
    from provisa.api.startup_seed import _adapt_view_ddl

    await _build(conn, KEY, T0)
    await _build(conn, KEY, T0 + timedelta(minutes=5), fail="boom", code="replica.x")
    await _build(conn, OTHER, T0)
    await build_state.record_index_plan(conn, OTHER, T0 + timedelta(seconds=30), _two_indexes())
    for name in ("replica_builds", "replica_build_health"):
        await conn.execute(_adapt_view_ddl(_OPS_REPORT_VIEWS[name]))
    await conn.execute(_adapt_view_ddl(_OPS_LOG_TABLE_VIEWS["replica_build_log"]))

    async def rows(sql):
        return [tuple(r) for r in (await conn.execute_core(text(sql))).fetchall()]

    assert await rows(
        "SELECT id, status, failed_attempts, error_code, error_message, rows_copied, "
        "indexes_wanted, indexes_built, indexes_failed FROM replica_builds ORDER BY id"
    ) == [
        ("src.public.customers", "idle", 0, None, None, 100, 2, 0, 0),
        # A build's claim starts its count again: the failed one copied none.
        ("src.public.orders", "failed", 1, "replica.x", "boom", 0, None, None, None),
    ]
    assert await rows(
        "SELECT source_id, day, build_count, failure_count, failed_replicas "
        "FROM replica_build_health"
    ) == [("src", "2026-10-15", 3, 1, 1)]
    assert await rows("SELECT table_name, outcome FROM replica_build_log_ops ORDER BY id") == [
        ("orders", "completed"),
        ("orders", "failed"),
        ("customers", "completed"),
    ]


def _two_indexes():
    from provisa.federation.replica_indexes import IndexSpec

    return [IndexSpec("rx_pk", ("id",), True), IndexSpec("rx_name", ("name",))]
