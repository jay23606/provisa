# Copyright (c) 2026 Kenneth Stott
# Canary: f723c6d9-cf66-4a8e-a93e-1fd20ea104ff
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Changes to several landed tables that belong together: applied in the order given, and in
one transaction where the store has one, so a reader never sees a message without its
recipients."""

from __future__ import annotations

import asyncio

import duckdb
import pytest

from provisa.federation.change_group import Change, TableChanges, ordered

pytestmark = pytest.mark.unit

MESSAGES = [("id", "text"), ("subject", "text")]
RECIPIENTS = [("message_id", "text"), ("position", "bigint"), ("address", "text")]


def _group(messages: list[Change], recipients: list[Change]) -> dict[str, TableChanges]:
    return {
        "messages": TableChanges("mail", "messages", MESSAGES, ["id"], messages),
        "message_recipients": TableChanges(
            "mail", "message_recipients", RECIPIENTS, ["message_id", "position"], recipients
        ),
    }


def _added() -> dict[str, TableChanges]:
    return _group(
        [Change("upsert", {"id": "m1", "subject": "hello"})],
        [
            Change("upsert", {"message_id": "m1", "position": 1, "address": "a@x.test"}),
            Change("upsert", {"message_id": "m1", "position": 2, "address": "b@x.test"}),
        ],
    )


# --- the order that keeps a reader from a torn row where there is no transaction ---


def test_rows_are_added_dependants_first_and_the_table_readers_start_from_last():
    assert [c.table for c in ordered(_added(), head="messages")] == [
        "message_recipients",
        "messages",
    ]


def test_rows_are_removed_from_the_table_readers_start_from_first():
    gone = _group(
        [Change("delete", {"id": "m1"})],
        [Change("delete", {"message_id": "m1", "position": 1})],
    )
    assert [c.table for c in ordered(gone, head="messages", removed=True)] == [
        "messages",
        "message_recipients",
    ]


def test_a_table_with_nothing_to_do_is_left_out():
    only = _group([], [Change("upsert", {"message_id": "m1", "position": 1, "address": "a"})])
    assert [c.table for c in ordered(only, head="messages")] == ["message_recipients"]


# --- one transaction on an embedded DuckDB store ---


def _counts(db: str) -> tuple[int, ...]:
    con = duckdb.connect(db, read_only=True)
    try:
        return tuple(
            con.execute(f'SELECT count(*) FROM mail."{table}"').fetchone()[0]
            for table in ("messages", "message_recipients")
        )
    finally:
        con.close()


class _Refuses:
    """A change whose row cannot be read: the write of its table fails."""

    operation = "upsert"

    @property
    def row(self):
        raise RuntimeError("the message's own write fails")


def test_a_group_lands_in_every_table_of_a_duckdb_store(tmp_path):
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    _SyncedStore(db).apply_change_group(ordered(_added(), head="messages"))
    assert _counts(db) == (1, 2)


def test_a_group_that_fails_part_way_changes_no_table_of_a_duckdb_store(tmp_path):
    """The recipients are written first; the message's own write then fails. Without one
    transaction the recipients would stay, a message's rows with no message."""
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    broker = _SyncedStore(db)
    broker.apply_change_group(ordered(_added(), head="messages"))
    more = _group(
        [_Refuses()],  # type: ignore[list-item]
        [Change("upsert", {"message_id": "m2", "position": 1, "address": "c@x.test"})],
    )
    with pytest.raises(RuntimeError, match="own write fails"):
        broker.apply_change_group(ordered(more, head="messages"))
    assert _counts(db) == (1, 2)  # m2's recipients did not stay


def test_removing_and_adding_in_one_group_leaves_each_key_as_last_said(tmp_path):
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    broker = _SyncedStore(db)
    broker.apply_change_group(ordered(_added(), head="messages"))
    changed = _group(
        [Change("upsert", {"id": "m1", "subject": "hello again"})],
        [
            Change("delete", {"message_id": "m1", "position": 2}),
            Change("upsert", {"message_id": "m1", "position": 1, "address": "z@x.test"}),
        ],
    )
    broker.apply_change_group(ordered(changed, head="messages"))
    # Applied twice (a crash before the position was kept re-reads the same changes): the same.
    broker.apply_change_group(ordered(changed, head="messages"))
    assert _counts(db) == (1, 1)
    con = duckdb.connect(db, read_only=True)
    try:
        assert con.execute('SELECT subject FROM mail."messages"').fetchall() == [("hello again",)]
        assert con.execute('SELECT address FROM mail."message_recipients"').fetchall() == [
            ("z@x.test",)
        ]
    finally:
        con.close()


# --- one transaction on a store written through SQLAlchemy ---


def test_a_group_that_fails_part_way_changes_no_table_of_a_sqlalchemy_store(tmp_path):
    import sqlalchemy as sa

    from provisa.federation.sqlalchemy_runtime import SqlAlchemyFederationRuntime

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'store.db'}")
    runtime = SqlAlchemyFederationRuntime.__new__(SqlAlchemyFederationRuntime)
    runtime._sa = engine  # the engine's own store connection

    def group(changes: dict[str, TableChanges]) -> list[TableChanges]:
        # SQLite has no schemas: the tables are written unqualified.
        return [
            TableChanges("", c.table, c.columns, c.pk_columns, c.events)
            for c in ordered(changes, head="messages")
        ]

    asyncio.run(runtime.apply_change_group(group(_added())))

    more = _group(
        [_Refuses()],  # type: ignore[list-item]
        [Change("upsert", {"message_id": "m2", "position": 1, "address": "c@x.test"})],
    )
    with pytest.raises(RuntimeError, match="own write fails"):
        asyncio.run(runtime.apply_change_group(group(more)))
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM messages")).scalar() == 1
        assert conn.execute(sa.text("SELECT count(*) FROM message_recipients")).scalar() == 2
    engine.dispose()


# --- rows named by part of their key ---


def _replaced() -> dict[str, TableChanges]:
    """m1 changed: its recipients are replaced whole, whatever positions it had."""
    return {
        "messages": TableChanges(
            "mail", "messages", MESSAGES, ["id"], [Change("upsert", {"id": "m1", "subject": "new"})]
        ),
        "message_recipients": TableChanges(
            "mail",
            "message_recipients",
            RECIPIENTS,
            ["message_id", "position"],
            [Change("upsert", {"message_id": "m1", "position": 1, "address": "only@x.test"})],
            delete_where=[{"message_id": "m1"}],
        ),
    }


def test_a_set_of_rows_is_replaced_whole_by_part_of_its_key_on_duckdb(tmp_path):
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    broker = _SyncedStore(db)
    other = _group(
        [Change("upsert", {"id": "m9", "subject": "another"})],
        [Change("upsert", {"message_id": "m9", "position": 1, "address": "kept@x.test"})],
    )
    for group in (_added(), other, _replaced(), _replaced()):  # the last one applied twice
        broker.apply_change_group(ordered(group, head="messages"))
    con = duckdb.connect(db, read_only=True)
    try:
        assert con.execute(
            'SELECT message_id, address FROM mail."message_recipients" ORDER BY 1'
        ).fetchall() == [("m1", "only@x.test"), ("m9", "kept@x.test")]
    finally:
        con.close()


def test_a_set_of_rows_is_removed_by_part_of_its_key_before_any_table_exists(tmp_path):
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    gone = {
        "message_recipients": TableChanges(
            "mail",
            "message_recipients",
            RECIPIENTS,
            ["message_id", "position"],
            delete_where=[{"message_id": "never-there"}],
        )
    }
    _SyncedStore(db).apply_change_group(ordered(gone, head="messages", removed=True))


def test_a_set_of_rows_is_replaced_whole_by_part_of_its_key_on_a_sqlalchemy_store(tmp_path):
    import sqlalchemy as sa

    from provisa.federation.sqlalchemy_runtime import SqlAlchemyFederationRuntime

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'store.db'}")
    runtime = SqlAlchemyFederationRuntime.__new__(SqlAlchemyFederationRuntime)
    runtime._sa = engine

    def group(changes: dict[str, TableChanges]) -> list[TableChanges]:
        return [
            TableChanges("", c.table, c.columns, c.pk_columns, c.events, c.delete_where)
            for c in ordered(changes, head="messages")
        ]

    for changes in (_added(), _replaced()):
        asyncio.run(runtime.apply_change_group(group(changes)))
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT address FROM message_recipients")).fetchall() == [
            ("only@x.test",)
        ]
    engine.dispose()


def test_a_removal_that_names_no_column_or_an_unknown_one_is_refused():
    with pytest.raises(ValueError, match="would empty the table"):
        TableChanges("mail", "messages", MESSAGES, ["id"], delete_where=[{}])
    with pytest.raises(ValueError, match="names no column"):
        TableChanges("mail", "messages", MESSAGES, ["id"], delete_where=[{"nope": 1}])
