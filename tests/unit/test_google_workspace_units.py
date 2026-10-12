# Copyright (c) 2026 Kenneth Stott
# Canary: 1d60f8c0-7e63-4629-984f-452e39155e72
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Gmail mailbox read as units written in place (REQ-1923): from its start a page at a time,
or as the one unit of what Gmail's history says happened since the last read.

Google is a stand-in throughout; nothing here reaches it.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import httpx
import pytest

from provisa.core import canonical_mail as cm
from provisa.federation.mail_units import Part, ReplicaUnitJob
from provisa.google_workspace import loader, units
from provisa.google_workspace.gmail import COST, Gmail, GmailNotFound, GmailRefused, QuotaExhausted
from provisa.google_workspace.loader import MESSAGE_TABLES, Reading, _Threads, _messages
from provisa.google_workspace.settings import MailSettings
from tests.unit.test_google_workspace_loader import ACCOUNT, FULL, MAILBOX, T0, FakeGmail, _mail

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

KEY = {"provider": "google", "account": ACCOUNT}
HISTORY = "1000"  # the mailbox's history id as its read begins (FakeGmail.profile)


def _added(message_id: str, thread: str) -> dict:
    return {"messagesAdded": [{"message": {"id": message_id, "threadId": thread}}]}


def _deleted(message_id: str, thread: str) -> dict:
    return {"messagesDeleted": [{"message": {"id": message_id, "threadId": thread}}]}


def _relabelled(message_id: str, thread: str, kind: str = "labelsAdded") -> dict:
    return {kind: [{"message": {"id": message_id, "threadId": thread}, "labelIds": ["STARRED"]}]}


class Mailbox(FakeGmail):
    """A mailbox that also answers its history and its threads."""

    def __init__(self, mailbox=None, pages=None, records=None, history_gone=False) -> None:
        super().__init__(mailbox, pages=pages)
        self.records = records or []
        self.history_gone = history_gone
        self.asked_since: list[str] = []
        self.threads_asked: list[str] = []

    async def label_ids(self, names: tuple[str, ...]) -> list[str]:
        return [{"Clients": "Label_7"}[name] for name in names]

    async def history(self, since: str):
        self.asked_since.append(since)
        if self.history_gone:
            raise GmailNotFound(ACCOUNT, "history.list", 404, "notFound")
        # Two pages, to show every page is read.
        yield self.records[:1]
        yield self.records[1:]

    async def thread(self, thread_id: str) -> dict:
        self.threads_asked.append(thread_id)
        messages = [m for m in self.mailbox.values() if m["threadId"] == thread_id]
        if not messages:
            raise GmailNotFound(ACCOUNT, "threads.get", 404, "notFound")
        return {"id": thread_id, "messages": messages}


async def _units(gmail, kept=None, mail: MailSettings = FULL, tables=MESSAGE_TABLES):
    unreadable: list[str] = []
    found = [
        unit
        async for unit in units.mailbox_units(
            gmail, mail, tables, kept, HISTORY, unreadable, threads=_Threads, messages=_messages
        )
    ]
    return found, unreadable


def _ids(unit: cm.Unit, table: str, column: str = "id") -> list:
    return [row[column] for row in unit.rows.get(table, [])]


class TestTheClient:
    async def _gmail(self, *answers):
        asked: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            asked.append(request)
            answer = answers[len(asked) - 1]
            return (
                answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)
            )

        async def token() -> str:
            return "made-up-access-token"

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return Gmail(ACCOUNT, token, client), asked

    async def test_history_is_read_to_its_last_page_from_the_record_given(self):
        gmail, asked = await self._gmail(
            {"history": [{"id": "1"}], "nextPageToken": "p2"}, {"history": [{"id": "2"}]}
        )
        pages = [page async for page in gmail.history("900")]
        assert pages == [[{"id": "1"}], [{"id": "2"}]]
        assert asked[0].url.params["startHistoryId"] == "900"
        assert asked[1].url.params["pageToken"] == "p2"
        assert asked[0].url.path.endswith(f"/users/{ACCOUNT}/history")

    async def test_a_history_record_google_no_longer_has_is_said_as_gone(self):
        gmail, _ = await self._gmail(httpx.Response(404, json={"error": {"errors": []}}))
        with pytest.raises(GmailNotFound):
            [page async for page in gmail.history("1")]

    async def test_a_mailbox_nothing_happened_to_has_no_history(self):
        gmail, _ = await self._gmail({"historyId": "1000"})
        assert [page async for page in gmail.history("1000")] == [[]]

    async def test_a_thread_is_asked_for_with_its_messages_headers(self):
        gmail, asked = await self._gmail({"id": "t1", "messages": []})
        assert await gmail.thread("t1") == {"id": "t1", "messages": []}
        assert asked[0].url.path.endswith("/threads/t1")
        assert asked[0].url.params["format"] == "metadata"

    async def test_both_calls_are_priced_as_google_prices_them(self):
        assert (COST["history.list"], COST["threads.get"]) == (2, 10)


class TestWhatASourceHolds:
    async def test_a_message_in_spam_or_the_bin_is_not_held_unless_the_source_takes_those(self):
        spam = {"labelIds": ["SPAM"], "internalDate": str(T0)}
        assert units.held(spam, FULL, []) is False
        assert units.held(spam, MailSettings("full", None, (), None, True), []) is True
        assert units.held({"labelIds": ["TRASH"]}, FULL, []) is False

    async def test_a_message_must_carry_every_label_the_source_names(self):
        message = {"labelIds": ["INBOX", "Label_7"]}
        assert units.held(message, FULL, ["Label_7"]) is True
        assert units.held(message, FULL, ["Label_7", "Label_9"]) is False

    async def test_a_message_received_before_the_sources_first_day_is_not_held(self):
        since = MailSettings("full", None, (), dt.date(2026, 1, 2), False)
        assert units.held({"labelIds": [], "internalDate": str(T0)}, since, []) is False
        later = str(T0 + 24 * 3_600_000)
        assert units.held({"labelIds": [], "internalDate": later}, since, []) is True


class TestAMailboxFromItsStart:
    async def test_it_is_cleared_then_given_a_page_at_a_time_then_its_threads_and_its_place(self):
        gmail = Mailbox(pages=[["m1", "m2"], ["m3"]])
        found, _ = await _units(gmail)
        first, page1, page2, last = found
        # What an earlier read left of the mailbox goes first, in every table, with what was
        # kept of where that read reached.
        assert first.removed == {table: [KEY] for table in MESSAGE_TABLES}
        assert (first.forget, first.rows, first.links, first.last) == (True, {}, {}, False)
        assert _ids(page1, "messages") == ["m1", "m2"] and _ids(page2, "messages") == ["m3"]
        assert set(page1.rows) == {
            "messages",
            "message_recipients",
            "message_folders",
            "attachments",
        }
        assert not page1.removed and not page1.links and not page1.last
        # A thread is all its messages: added up over the whole read, given at its end.
        assert {r["id"]: r["message_count"] for r in last.rows["threads"]} == {"t1": 2, "t2": 1}
        # Where the read reached is where the mailbox stood when it BEGAN.
        assert (last.links, last.last) == ({"": HISTORY}, True)
        assert gmail.asked_since == []

    async def test_only_the_tables_asked_for_are_given(self):
        found, _ = await _units(Mailbox(), tables=("message_folders", "threads"))
        assert found[0].removed == {"message_folders": [KEY], "threads": [KEY]}
        assert set(found[1].rows) == {"message_folders"}
        assert set(found[-1].rows) == {"threads"}

    async def test_a_mailbox_with_no_mail_still_says_where_it_stands(self):
        found, _ = await _units(Mailbox(mailbox={}, pages=[[]]))
        assert (found[-1].links, found[-1].last, found[-1].rows) == (
            {"": HISTORY},
            True,
            {"threads": []},
        )

    async def test_a_history_record_google_no_longer_has_reads_the_mailbox_from_its_start(self):
        gmail = Mailbox(history_gone=True)
        found, _ = await _units(gmail, kept={"": "5"})
        assert gmail.asked_since == ["5"]
        assert found[0].forget and found[0].removed["messages"] == [KEY]
        assert _ids(found[1], "messages") == ["m1", "m2", "m3"]

    async def test_a_source_that_narrows_by_search_is_always_read_from_its_start(self):
        """Only Google can say what a search matches, so history cannot say what the source
        holds."""
        gmail = Mailbox(records=[_added("m1", "t1")])
        searched = MailSettings("full", "from:bo@example.test", (), None, False)
        found, _ = await _units(gmail, kept={"": "5"}, mail=searched)
        assert gmail.asked_since == [] and found[0].forget


class TestItsChanges:
    async def test_nothing_happened_is_one_unit_that_moves_its_place_and_writes_nothing(self):
        gmail = Mailbox(records=[])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert gmail.asked_since == ["900"]
        assert (unit.rows, unit.removed, unit.forget) == ({}, {}, False)
        assert (unit.links, unit.last) == ({"": HISTORY}, True)
        assert gmail.asked == []  # no message was fetched

    async def test_a_message_added_or_relabelled_is_fetched_again_and_its_dependants_replaced(self):
        gmail = Mailbox(records=[_added("m3", "t2"), _relabelled("m1", "t1", "labelsRemoved")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert sorted(_ids(unit, "messages")) == ["m1", "m3"]
        assert [m for m, _ in gmail.asked] == ["m3", "m1"]  # each once, and no other
        named = [{**KEY, "message_id": "m3"}, {**KEY, "message_id": "m1"}]
        assert unit.removed == {table: named for table in units.DEPENDANTS}
        assert "messages" not in unit.removed  # a message that stays is replaced by its key
        assert sorted(_ids(unit, "message_folders", "message_id")) == ["m1", "m1", "m3", "m3"]
        # Each of their threads is read again whole: t1 still has both its messages.
        assert gmail.threads_asked == ["t1", "t2"]
        assert {r["id"]: r["message_count"] for r in unit.rows["threads"]} == {"t1": 2, "t2": 1}

    async def test_a_message_deleted_goes_with_its_dependants_and_its_thread_is_made_again(self):
        mailbox = {k: v for k, v in MAILBOX.items() if k != "m2"}
        gmail = Mailbox(mailbox=mailbox, records=[_deleted("m2", "t1")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert unit.removed["messages"] == [{**KEY, "id": "m2"}]
        assert unit.removed["attachments"] == [{**KEY, "message_id": "m2"}]
        assert "messages" not in unit.rows and gmail.asked == []
        # Gmail's history names a deleted message's thread, so the thread is exact.
        assert [(r["id"], r["message_count"]) for r in unit.rows["threads"]] == [("t1", 1)]
        assert "threads" not in unit.removed

    async def test_a_thread_whose_last_message_went_goes_too(self):
        mailbox = {k: v for k, v in MAILBOX.items() if k != "m3"}
        gmail = Mailbox(mailbox=mailbox, records=[_deleted("m3", "t2")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert unit.removed["threads"] == [{**KEY, "id": "t2"}]
        assert "threads" not in unit.rows

    async def test_a_message_gone_by_the_time_it_is_fetched_is_a_message_deleted(self):
        mailbox = {k: v for k, v in MAILBOX.items() if k != "m3"}
        gmail = Mailbox(mailbox=mailbox, records=[_added("m3", "t2")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert unit.removed["messages"] == [{**KEY, "id": "m3"}]
        assert unit.removed["threads"] == [{**KEY, "id": "t2"}]

    async def test_a_message_added_then_deleted_is_only_deleted_and_the_reverse(self):
        gmail = Mailbox(records=[_added("m1", "t1"), _deleted("m1", "t1"), _added("m1", "t1")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert _ids(unit, "messages") == ["m1"] and "messages" not in unit.removed

    async def test_a_message_no_longer_among_what_the_source_holds_is_removed(self):
        """Its label was taken off, or it went to the bin: the message exists and is not the
        source's any more."""
        binned = {**MAILBOX, "m3": {**MAILBOX["m3"], "labelIds": ["TRASH"]}}
        gmail = Mailbox(mailbox=binned, records=[_relabelled("m3", "t2")])
        (unit,), _ = await _units(gmail, kept={"": "900"})
        assert unit.removed["messages"] == [{**KEY, "id": "m3"}]
        assert unit.removed["threads"] == [{**KEY, "id": "t2"}]  # none of its messages is held
        labelled = MailSettings("full", None, ("Clients",), None, False)
        off = {**MAILBOX, "m1": {**MAILBOX["m1"], "labelIds": ["INBOX"]}}
        gmail = Mailbox(mailbox=off, records=[_relabelled("m1", "t1", "labelsRemoved")])
        (unit,), _ = await _units(gmail, kept={"": "900"}, mail=labelled)
        assert unit.removed["messages"] == [{**KEY, "id": "m1"}]
        # Its thread keeps the message that still carries the label.
        assert [(r["id"], r["message_count"]) for r in unit.rows["threads"]] == [("t1", 1)]

    async def test_a_message_kept_without_its_text_is_counted(self):
        broken = _mail("m9", "t9", T0, "Kept")
        broken["payload"]["parts"][0]["headers"] = [
            {"name": "Content-Type", "value": "text/plain; charset=x-made-up"}
        ]
        gmail = Mailbox(mailbox={**MAILBOX, "m9": broken}, records=[_added("m9", "t9")])
        (unit,), unreadable = await _units(gmail, kept={"": "900"})
        assert unreadable == ["m9"] and _ids(unit, "messages") == ["m9"]


# ------------------------------------------------------------------ the pass over mailboxes


class StateStore:
    """Where a read's place is kept, as ``federation.mail_sync_state`` keeps it."""

    def __init__(self, rows=None) -> None:
        self.rows: dict[tuple[str, str, str], str] = dict(rows or {})

    async def kept(self):
        return dict(self.rows)

    async def keep_part(self, account, links, kind):
        for scope, link in links.items():
            self.rows[(account.lower(), scope, kind)] = link

    async def forget_mailbox(self, account):
        self.rows = {k: v for k, v in self.rows.items() if k[0] != account.lower()}


class Boxes(Mailbox):
    """One of several mailboxes: ``boxes`` says how each is."""

    boxes: dict[str, dict] = {}

    def __init__(self, account, token, client, **_kw) -> None:
        box = Boxes.boxes[account]
        super().__init__(records=box.get("records"), history_gone=box.get("history_gone", False))
        self.account, self._box = account, box

    async def profile(self) -> dict:
        if self._box.get("refuse") is not None:
            raise self._box["refuse"]
        return {"emailAddress": self.account, "historyId": self._box["history"]}

    async def message_ids(self, mail):
        if self._box.get("fail_midway") is not None:
            yield list(MAILBOX)[:1]
            raise self._box["fail_midway"]
        yield list(MAILBOX)

    async def message(self, message_id, mail):
        answered = dict(MAILBOX[message_id])
        return answered


@pytest.fixture
def passes(monkeypatch):
    """A unit read over three mailboxes of the organisation and a place to keep where it
    reached."""
    Boxes.boxes = {
        "ada@example.test": {"history": "100"},
        "bo@example.test": {"history": "200"},
        "cy@example.test": {"history": "300"},
    }
    monkeypatch.setattr(loader, "Gmail", Boxes)
    store = StateStore()

    async def token(_account: str) -> str:
        return "made-up-access-token"

    def reading(accounts=None, organisation=True):
        return Reading(
            tuple(accounts or Boxes.boxes),
            FULL,
            token,
            organisation=organisation,
            at_once=1,
            kept=store.kept,
            keep_part=store.keep_part,
            forget_mailbox=store.forget_mailbox,
        )

    seen = SimpleNamespace(store=store, reading=reading(), make=reading)

    async def connect(_source):
        return seen.reading

    seen.read = lambda: loader._UnitsRead(connect, SimpleNamespace(id="org-mail"), MESSAGE_TABLES)
    return seen


async def _run(read) -> tuple[list[cm.Unit], list[list]]:
    """The pass through the real job that writes units, with the store's writes recorded."""
    applied: list[list] = []
    given: list[cm.Unit] = []

    async def apply(group):
        applied.append(group)

    async def written(unit):
        given.append(unit)

    parts = {
        t: Part("mail", t, list(cm.landing_columns(t)), cm.key_columns(t), cm.LANDED_AT)
        for t in MESSAGE_TABLES
    }
    await ReplicaUnitJob(read, parts, apply, written=written).run()
    return given, applied


class TestAPassOverMailboxes:
    async def test_the_loader_gives_its_read_in_units(self, passes):
        async def connect(_source):
            return passes.reading

        mail_loader = loader.make_google_workspace_loader(connect)
        read = mail_loader.replica_unit_source(
            SimpleNamespace(id="org-mail"), list(MESSAGE_TABLES), {}
        )
        assert isinstance(read, loader._UnitsRead)

    async def test_each_mailbox_is_read_from_its_start_and_its_place_kept_once_written(
        self, passes
    ):
        read = passes.read()
        given, applied = await _run(read)
        assert read.total == 3
        assert {u.account for u in given} == set(Boxes.boxes)
        assert applied  # written through the job, in the tables' own order
        # Each mailbox's place is its history id as its read began, kept under the mailbox.
        assert passes.store.rows == {
            ("ada@example.test", "", "delta"): "100",
            ("bo@example.test", "", "delta"): "200",
            ("cy@example.test", "", "delta"): "300",
        }
        assert read.notes() == []

    async def test_the_next_pass_asks_each_mailbox_only_what_changed_since(self, passes):
        await _run(passes.read())
        Boxes.boxes["ada@example.test"].update(history="150", records=[_added("m1", "t1")])
        Boxes.boxes["bo@example.test"].update(history="200", records=[])
        Boxes.boxes["cy@example.test"].update(history="300", records=[])
        given, _ = await _run(passes.read())
        # Only the mailbox something happened to writes anything.
        assert [(u.account, _ids(u, "messages")) for u in given] == [("ada@example.test", ["m1"])]
        assert passes.store.rows[("ada@example.test", "", "delta")] == "150"

    async def test_a_mailbox_the_source_no_longer_names_loses_its_rows_and_its_place(self, passes):
        await _run(passes.read())
        passes.reading = passes.make(["ada@example.test", "bo@example.test"])
        for box in Boxes.boxes.values():
            box["records"] = []
        given, _ = await _run(passes.read())
        (gone,) = given
        assert gone.account == "cy@example.test" and gone.forget
        assert gone.removed == {
            t: [{"provider": "google", "account": "cy@example.test"}] for t in MESSAGE_TABLES
        }
        assert not any(key[0] == "cy@example.test" for key in passes.store.rows)

    async def test_a_mailbox_that_fails_part_way_is_named_and_the_others_go_on(self, passes):
        Boxes.boxes["bo@example.test"]["fail_midway"] = GmailRefused(
            "bo@example.test", "messages.get", 403, "domainPolicy"
        )
        read = passes.read()
        given, _ = await _run(read)
        # What it gave before it failed is written and stays; it is not said to be read to
        # its end, so its place is not kept and its next read begins again.
        assert ("bo@example.test", "", "delta") not in passes.store.rows
        assert {k[0] for k in passes.store.rows} == {"ada@example.test", "cy@example.test"}
        (note,) = read.notes()
        assert (note.code, note.params["accounts"]) == (
            "replication.mailboxes_failed",
            ["bo@example.test"],
        )
        assert any(u.account == "bo@example.test" for u in given)

    async def test_when_every_mailbox_fails_the_pass_fails_with_the_last_refusal(self, passes):
        for box in Boxes.boxes.values():
            box["fail_midway"] = GmailRefused("x", "messages.get", 403, "domainPolicy")
        with pytest.raises(RuntimeError, match="none of the 3 mailbox.*403 domainPolicy"):
            await _run(passes.read())

    async def test_the_projects_allowance_fails_the_pass_whatever_landed(self, passes):
        Boxes.boxes["bo@example.test"]["fail_midway"] = QuotaExhausted(
            "bo@example.test", "messages.get", 403, "dailyLimitExceeded"
        )
        with pytest.raises(QuotaExhausted):
            await _run(passes.read())

    async def test_one_mailboxes_refusal_fails_its_read(self, passes):
        """A source of one mailbox has no other to go on with."""
        Boxes.boxes["ada@example.test"]["fail_midway"] = GmailRefused(
            "ada@example.test", "messages.get", 403, "domainPolicy"
        )
        passes.reading = passes.make(["ada@example.test"], organisation=False)
        with pytest.raises(GmailRefused):
            await _run(passes.read())

    async def test_a_mailbox_google_will_not_let_be_read_is_left_out_and_kept_as_that(self, passes):
        await _run(passes.read())
        Boxes.boxes["cy@example.test"]["refuse"] = GmailRefused(
            "cy@example.test", "getProfile", 400, "failedPrecondition: Mail service not enabled"
        )
        for box in Boxes.boxes.values():
            box["records"] = []
        read = passes.read()
        await _run(read)
        (note,) = read.notes()
        assert note.code == "replication.mailboxes_left_out"
        await read.committed()
        # In place of where its earlier read reached: it is read from its start if it returns.
        assert passes.store.rows[("cy@example.test", "", "probe")] == "left_out"
        assert ("cy@example.test", "", "delta") not in passes.store.rows
        assert ("ada@example.test", "", "delta") in passes.store.rows

    async def test_a_read_with_nowhere_to_keep_its_place_is_refused(self, passes):
        async def token(_account: str) -> str:
            return "t"

        passes.reading = Reading(("ada@example.test",), FULL, token)
        with pytest.raises(RuntimeError, match="needs somewhere to keep where it reached"):
            await _run(passes.read())
