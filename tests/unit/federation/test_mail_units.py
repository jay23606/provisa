# Copyright (c) 2026 Kenneth Stott
# Canary: 4954252a-d5ec-454e-958e-abb0e4ac2289
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A mail source's replicas kept in place a unit at a time: each unit's tables written
together and queryable at once, rows first and the place the read reached second, every
unit under one stamp later than the last."""

from __future__ import annotations

import duckdb
import pytest

from provisa.core import canonical_mail as cm
from provisa.federation import mail_units
from provisa.federation.mail_units import Part, ReplicaUnitJob, changes_of

pytestmark = pytest.mark.unit

A, B = "ada@x.test", "bo@x.test"
MESSAGES = [("provider", "text"), ("account", "text"), ("id", "text"), ("subject", "text")]
RECIPIENTS = [
    ("provider", "text"),
    ("account", "text"),
    ("message_id", "text"),
    ("kind", "text"),
    ("position", "bigint"),
    ("address", "text"),
]
STAMP = (cm.LANDED_AT, "timestamp")
PARTS = {
    "messages": Part("mail", "messages", [*MESSAGES, STAMP]),
    "message_recipients": Part("mail", "message_recipients", [*RECIPIENTS, STAMP]),
}


def _message(account: str, n: int, subject: str = "s") -> dict:
    return {"provider": "microsoft", "account": account, "id": f"m{n}", "subject": subject}


def _recipient(account: str, n: int, position: int = 1, address: str = "to@x.test") -> dict:
    return {
        "provider": "microsoft",
        "account": account,
        "message_id": f"m{n}",
        "kind": "to",
        "position": position,
        "address": address,
    }


def _of(account: str, **key) -> dict:
    return {"provider": "microsoft", "account": account, **key}


def _page(account: str, *numbers: int, **over) -> cm.Unit:
    return cm.Unit(
        account,
        rows={
            "messages": [_message(account, n) for n in numbers],
            "message_recipients": [_recipient(account, n) for n in numbers],
        },
        removed={"message_recipients": [_of(account, message_id=f"m{n}") for n in numbers]},
        **over,
    )


class Source:
    """Gives the units it was made with, and records what it is told to keep and forget."""

    def __init__(self, *units: cm.Unit) -> None:
        self._units = units
        self.kept: list[tuple[str, dict]] = []
        self.forgotten: list[str] = []
        self.events: list[str] = []

    async def units(self):
        for unit in self._units:
            yield unit

    async def keep(self, account, links):
        self.kept.append((account, dict(links)))
        self.events.append(f"keep {account}")

    async def forget(self, account):
        self.forgotten.append(account)
        self.events.append(f"forget {account}")


@pytest.fixture
def store(tmp_path):
    from provisa.federation.materialize_broker import _SyncedStore

    db = str(tmp_path / "store.duckdb")
    broker = _SyncedStore(db)

    async def apply(group):
        broker.apply_change_group(group)

    def read(sql: str) -> list[tuple]:
        con = duckdb.connect(db, read_only=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    return apply, read


async def test_each_unit_is_queryable_as_soon_as_it_is_written(store):
    apply, read = store
    seen: list[int] = []

    async def written(unit):
        seen.append(read('SELECT count(*) FROM mail."messages"')[0][0])

    source = Source(_page(A, 1, 2), _page(A, 3), _page(B, 1, last=True))
    landed = await ReplicaUnitJob(source, PARTS, apply, written=written).run()
    assert seen == [2, 3, 4]  # the table fills unit by unit; nothing waits for the last
    assert landed.rows == {"messages": 4, "message_recipients": 4} and landed.mailboxes == 1


async def test_rows_are_written_before_the_place_the_read_reached_is_kept(store):
    apply, read = store
    order: list[str] = []

    async def recording(group):
        await apply(group)
        order.append("rows")

    source = Source(_page(A, 1, links={"inbox": "link-1"}))
    source.events = order
    await ReplicaUnitJob(source, PARTS, recording).run()
    assert order == ["rows", f"keep {A}"]
    assert source.kept == [(A, {"inbox": "link-1"})]


async def test_a_unit_that_cannot_be_written_keeps_no_place_and_stops_the_pass(store):
    apply, read = store

    async def refuses(group):
        raise RuntimeError("the store refused")

    source = Source(_page(A, 1, links={"inbox": "link-1"}), _page(A, 2))
    with pytest.raises(RuntimeError, match="the store refused"):
        await ReplicaUnitJob(source, PARTS, refuses).run()
    assert source.kept == []  # its changes are read again


async def test_a_unit_with_only_a_place_writes_nothing_and_keeps_it(store):
    apply, _read = store
    called: list[object] = []

    async def counting(group):
        called.append(group)

    source = Source(cm.Unit(A, links={"inbox": "link"}, last=True))
    landed = await ReplicaUnitJob(source, PARTS, counting).run()
    assert called == [] and source.kept == [(A, {"inbox": "link"})]
    assert landed.wrote is False and landed.mailboxes == 1


async def test_a_mailbox_read_again_from_its_start_is_cleared_and_its_place_forgotten(store):
    apply, read = store
    await ReplicaUnitJob(Source(_page(A, 1, 2), _page(B, 1)), PARTS, apply).run()
    again = Source(
        cm.Unit(A, removed={name: [_of(A)] for name in PARTS}, forget=True),
        _page(A, 2, last=True),
    )
    await ReplicaUnitJob(again, PARTS, apply).run()
    assert again.forgotten == [A]
    assert read('SELECT account, id FROM mail."messages" ORDER BY 1, 2') == [(A, "m2"), (B, "m1")]
    assert read('SELECT account, message_id FROM mail."message_recipients" ORDER BY 1, 2') == [
        (A, "m2"),
        (B, "m1"),
    ]


async def test_what_changed_is_applied_in_place_a_removed_message_with_its_dependants(store):
    apply, read = store
    await ReplicaUnitJob(Source(_page(A, 1, 2, 3)), PARTS, apply).run()
    changed = cm.Unit(
        A,
        rows={
            "messages": [_message(A, 2, "edited")],
            "message_recipients": [_recipient(A, 2, 1, "new@x.test")],
        },
        removed={
            "messages": [_of(A, id="m1")],
            "message_recipients": [_of(A, message_id="m1"), _of(A, message_id="m2")],
        },
        links={"inbox": "next"},
        last=True,
    )
    for _ in range(2):  # written twice, as after a stop before the place was kept: the same
        await ReplicaUnitJob(Source(changed), PARTS, apply).run()
    assert read('SELECT id, subject FROM mail."messages" ORDER BY 1') == [
        ("m2", "edited"),
        ("m3", "s"),
    ]
    assert read('SELECT message_id, address FROM mail."message_recipients" ORDER BY 1') == [
        ("m2", "new@x.test"),
        ("m3", "to@x.test"),
    ]


async def test_every_row_of_a_unit_carries_one_stamp_and_each_unit_a_later_one(store):
    apply, read = store
    await ReplicaUnitJob(Source(_page(A, 1, 2), _page(B, 1), _page(A, 3)), PARTS, apply).run()
    by_unit = read(
        f'SELECT min({cm.LANDED_AT}), max({cm.LANDED_AT}), count(*) FROM mail."messages" '
        f"GROUP BY {cm.LANDED_AT} ORDER BY 1"
    )
    assert [count for _lo, _hi, count in by_unit] == [2, 1, 1]
    stamps = [lo for lo, _hi, _count in by_unit]
    assert stamps == sorted(stamps) and len(set(stamps)) == 3
    # A unit's dependants carry its own stamp: it is delivered whole or not yet.
    assert {row[0] for row in read(f'SELECT {cm.LANDED_AT} FROM mail."message_recipients"')} == set(
        stamps
    )


def test_the_order_never_shows_a_message_without_its_dependants():
    """Where the store cannot write the tables as one: what is removed goes first, messages
    before their dependants; then dependants, each set replaced whole; then the messages."""
    unit = cm.Unit(
        A,
        rows={"messages": [_message(A, 2)], "message_recipients": [_recipient(A, 2)]},
        removed={
            "messages": [_of(A, id="m1")],
            "message_recipients": [_of(A, message_id="m1"), _of(A, message_id="m2")],
        },
    )
    group = changes_of(unit, PARTS, at=None)
    assert [(c.table, bool(c.delete_where), bool(c.events)) for c in group] == [
        ("messages", True, False),
        ("message_recipients", True, True),
        ("messages", False, True),
    ]
    assert group[0].pk_columns == list(cm.KEYS["messages"])


def test_a_table_that_is_not_replicated_is_left_out_and_an_unstamped_one_gets_no_stamp():
    unit = _page(A, 1)
    only = {"messages": Part("mail", "messages", MESSAGES)}  # registered before the stamp
    (changes,) = changes_of(unit, only, at="now")
    assert changes.table == "messages" and cm.LANDED_AT not in changes.events[0].row


async def test_the_first_write_and_each_finished_mailbox_are_told(store):
    apply, _read = store
    told: list[object] = []

    async def first():
        told.append("first")

    async def done(count):
        told.append(count)

    source = Source(_page(A, 1), _page(A, 2, last=True), _page(B, 1, last=True))
    await ReplicaUnitJob(source, PARTS, apply, first_write=first, mailbox_done=done).run()
    assert told == ["first", 1, 2]
    assert mail_units.METHOD == "apply_units"
