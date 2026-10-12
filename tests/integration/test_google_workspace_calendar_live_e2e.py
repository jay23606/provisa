# Copyright (c) 2026 Kenneth Stott
# Canary: 4a7c2e95-1d6b-4f38-8e02-b9c5d3a6f714
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Live Google Workspace calendars and tasks (REQ-1994), read and written, against a real
Workspace domain.

What it proves that a stand-in Google cannot: the service account is issued a token to read and
write a user's events and tasks (the domain has delegated the scopes); a write made through the
source's write route -- an event with a reminder, a series, one occurrence of it moved and
another cancelled, an attendee added and removed telling nobody, a task due on a day, done, then
removed -- is what the source's tables read back, row for row; and the change token of the
source's calendars and task lists moves when they are written.

It writes to the first test mailbox's primary calendar and to a task list it makes, and removes
everything it made when it ends, whether it passed or not. An event or task list it made in an
earlier run that did not end (its title carries the run marker) is removed first. No server,
engine or container is used: the loader and the write driver are driven directly, so run it with
the stack switched off:

    PYTEST_NO_DOCKER=1 .venv/bin/python3 -m pytest \\
        tests/integration/test_google_workspace_calendar_live_e2e.py -o addopts="" -q

Credentials
-----------
The same as tests/integration/test_google_workspace_live_e2e.py, with the service account's
domain-wide delegation also authorised for:

    https://www.googleapis.com/auth/calendar.calendarlist.readonly
    https://www.googleapis.com/auth/calendar.events
    https://www.googleapis.com/auth/tasks

  GWS_SERVICE_ACCOUNT_KEY_FILE, GWS_ADMIN_ADDRESS, GWS_TEST_MAILBOXES (the first is written to;
  a second, when named, is the attendee added and removed -- with nobody told).

In no CI lane, like the mail test; a credential that is not set fails it by name.
"""

# Requirements: REQ-1994
from __future__ import annotations

import asyncio
import datetime as dt
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from tests.env_creds import unset

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_warehouse,
    pytest.mark.requires_google_workspace,
]

_ENV = ("GWS_SERVICE_ACCOUNT_KEY_FILE", "GWS_ADMIN_ADDRESS", "GWS_TEST_MAILBOXES")
_HAVE_CREDS = all(os.environ.get(v) for v in _ENV)
pytestmark.append(pytest.mark.skipif(not _HAVE_CREDS, reason=f"not set: {unset(*_ENV)}"))

from provisa.core import canonical_mail as cm  # noqa: E402
from provisa.federation.mail_write import MailWriteDriver, WriteRefused  # noqa: E402
from provisa.google_workspace import calendar_read, directory, loader  # noqa: E402
from provisa.google_workspace import settings as gws  # noqa: E402
from provisa.google_workspace.calendar_write import GoogleWriter  # noqa: E402
from provisa.google_workspace.workspace_api import (  # noqa: E402
    CALENDAR_URL,
    TASKS_URL,
    WorkspaceApi,
)

#: Every title this test writes starts with this; a run's own marker follows it.
_MARK = "provisa-live-calendar"
_RUN = f"{_MARK}-{uuid.uuid4().hex[:8]}"
_SCOPES = (*gws.RESOURCE_SCOPES[gws.CALENDAR], *gws.RESOURCE_SCOPES[gws.TASKS])
_SOURCE = SimpleNamespace(id="gws-live-calendar", mapping={})


def _mailboxes() -> tuple[str, ...]:
    return tuple(
        a.strip().lower() for a in os.environ["GWS_TEST_MAILBOXES"].split(",") if a.strip()
    )


ADA = _mailboxes()[0] if _HAVE_CREDS else ""
OTHER = _mailboxes()[1] if _HAVE_CREDS and len(_mailboxes()) > 1 else None


@pytest.fixture(scope="module")
def account() -> directory.ServiceAccount:
    key = Path(os.environ["GWS_SERVICE_ACCOUNT_KEY_FILE"]).expanduser().read_text()
    return directory.ServiceAccount(key)


def _reading(account: directory.ServiceAccount) -> loader.Reading:
    async def as_user(address: str) -> str:
        return await asyncio.to_thread(account.token, address, _SCOPES)

    return loader.Reading((ADA,), None, as_user, organisation=True, at_once=1)


@asynccontextmanager
async def _api(account: directory.ServiceAccount):
    reading = _reading(account)

    async def token() -> str:
        return await reading.token(ADA)

    async with httpx.AsyncClient() as client:
        yield WorkspaceApi(ADA, token, client, quota_user=True)


def _driver(account: directory.ServiceAccount) -> MailWriteDriver:
    async def accounts() -> tuple[str, ...]:
        return (ADA,)

    @asynccontextmanager
    async def writer_for(_address: str):
        async with _api(account) as api:
            yield GoogleWriter(api, send_updates=False)

    return MailWriteDriver(cm.GOOGLE, accounts, writer_for)


def _rows(account: directory.ServiceAccount, table: str) -> list[dict]:
    """The table as the source reads it now, this run's rows only."""

    async def connect(_source):
        return _reading(account)

    load = loader.make_google_workspace_loader(connect)
    rows = asyncio.run(load(_SOURCE, SimpleNamespace(table_name=table)))
    return rows


def _ours(rows: list[dict], key: str = "title") -> list[dict]:
    return [r for r in rows if (r.get(key) or "").startswith(_RUN)]


def _run(sql: str, account: directory.ServiceAccount, params: list | None = None) -> int:
    result = asyncio.run(_driver(account).execute(sql, params))
    assert result.rowcount is not None
    return result.rowcount


async def _sweep(account: directory.ServiceAccount, everything: bool) -> None:
    """Remove what this run made, and what an earlier run that did not end left behind."""
    async with _api(account) as api:
        async for page in api.events("primary"):
            for item in page:
                title = item.get("summary") or ""
                if not title.startswith(_MARK) or item.get("recurringEventId"):
                    continue
                if not everything and title.startswith(_RUN):
                    continue
                await api.call(
                    "DELETE",
                    CALENDAR_URL + f"calendars/primary/events/{item['id']}",
                    params={"sendUpdates": "none"},
                    call="events.delete",
                )
        for task_list in await api.task_lists():
            title = task_list.get("title") or ""
            if title.startswith(_MARK) and (everything or not title.startswith(_RUN)):
                await api.call(
                    "DELETE",
                    TASKS_URL + f"users/@me/lists/{task_list['id']}",
                    call="tasklists.delete",
                )


@pytest.fixture(scope="module", autouse=True)
def cleaned(account):
    asyncio.run(_sweep(account, everything=False))
    yield
    asyncio.run(_sweep(account, everything=True))


@pytest.fixture(scope="module")
def task_list(account, cleaned) -> str:
    async def make() -> str:
        async with _api(account) as api:
            made = await api.call(
                "POST",
                TASKS_URL + "users/@me/lists",
                body={"title": f"{_RUN} list"},
                call="tasklists.insert",
            )
            return made["id"]

    return asyncio.run(make())


def _at(hours: int) -> str:
    start = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    return (start + dt.timedelta(days=2, hours=hours)).isoformat()


def test_an_event_written_with_its_reminder_reads_back(account):
    token_before = asyncio.run(calendar_read.change_token(_reading(account), "events"))
    assert (
        _run(
            'INSERT INTO "default"."events" (calendar_id, title, start_at, end_at, reminders) '
            "VALUES ('primary', $1, $2, $3, $4)",
            account,
            [
                f"{_RUN} single",
                _at(9),
                _at(10),
                '{"useDefault": false, "overrides": [{"method": "popup", "minutes": 7}]}',
            ],
        )
        == 1
    )
    (event,) = [r for r in _ours(_rows(account, "events")) if r["title"].endswith("single")]
    assert (event["provider"], event["account"], event["kind"]) == ("google", ADA, "single")
    assert event["reminders"]["overrides"] == [{"method": "popup", "minutes": 7}]
    assert asyncio.run(calendar_read.change_token(_reading(account), "events")) != token_before

    assert (
        _run(
            "UPDATE events SET title = $1 WHERE id = $2", account, [f"{_RUN} renamed", event["id"]]
        )
        == 1
    )
    assert [r["title"] for r in _ours(_rows(account, "events")) if r["id"] == event["id"]] == [
        f"{_RUN} renamed"
    ]


def test_one_occurrence_of_a_series_is_moved_and_another_cancelled(account):
    _run(
        "INSERT INTO events (calendar_id, title, start_at, end_at, recurrence) "
        "VALUES ('primary', $1, $2, $3, 'RRULE:FREQ=DAILY;COUNT=3')",
        account,
        [f"{_RUN} series", _at(11), _at(12)],
    )
    (series,) = [r for r in _ours(_rows(account, "events")) if r["title"].endswith("series")]
    assert (series["kind"], series["recurrence"]) == ("series_master", "RRULE:FREQ=DAILY;COUNT=3")
    second = series["start_at"] + dt.timedelta(days=1)
    third = series["start_at"] + dt.timedelta(days=2)
    with pytest.raises(WriteRefused, match="set on a series"):
        _run(
            "UPDATE events SET recurrence = 'RRULE:FREQ=WEEKLY' "
            "WHERE series_id = $1 AND original_start_at = $2",
            account,
            [series["id"], second.isoformat()],
        )
    assert (
        _run(
            "UPDATE events SET title = $1 WHERE series_id = $2 AND original_start_at = $3",
            account,
            [f"{_RUN} series moved", series["id"], second.isoformat()],
        )
        == 1
    )
    assert (
        _run(
            "DELETE FROM events WHERE series_id = $1 AND original_start_at = $2",
            account,
            [series["id"], third.isoformat()],
        )
        == 1
    )
    exceptions = {
        r["original_start_at"]: r
        for r in _rows(account, "events")
        if r["series_id"] == series["id"]
    }
    assert exceptions[second]["title"] == f"{_RUN} series moved"
    assert exceptions[second]["kind"] == "exception"
    assert exceptions[third]["is_cancelled"] is True


@pytest.mark.skipif(OTHER is None, reason="GWS_TEST_MAILBOXES names no second mailbox")
def test_an_attendee_is_added_and_removed_telling_nobody(account):
    (event,) = [r for r in _ours(_rows(account, "events")) if r["title"].endswith("renamed")]
    assert (
        _run(
            "INSERT INTO event_attendees (event_id, address, kind) VALUES ($1, $2, 'optional')",
            account,
            [event["id"], OTHER],
        )
        == 1
    )
    people = [r for r in _rows(account, "event_attendees") if r["event_id"] == event["id"]]
    assert [(p["address"], p["kind"]) for p in people] == [(OTHER, "optional")]
    assert (
        _run(
            "DELETE FROM event_attendees WHERE event_id = $1 AND address = $2",
            account,
            [event["id"], OTHER],
        )
        == 1
    )
    assert not [r for r in _rows(account, "event_attendees") if r["event_id"] == event["id"]]


def test_a_task_is_due_on_a_day_done_and_removed(account, task_list):
    token_before = asyncio.run(calendar_read.change_token(_reading(account), "tasks"))
    with pytest.raises(WriteRefused, match="reminder_at is not written"):
        _run(
            "INSERT INTO tasks (task_list_id, title, reminder_at) VALUES ($1, 't', '2026-10-13')",
            account,
            [task_list],
        )
    due = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    _run(
        "INSERT INTO tasks (task_list_id, title, notes, due_date) VALUES ($1, $2, 'n', $3)",
        account,
        [task_list, f"{_RUN} task", due],
    )
    (task,) = _ours(_rows(account, "tasks"))
    assert (task["status"], task["due_date"].isoformat(), task["task_list_id"]) == (
        "open",
        due,
        task_list,
    )
    assert asyncio.run(calendar_read.change_token(_reading(account), "tasks")) != token_before
    assert _run("UPDATE tasks SET status = 'done' WHERE id = $1", account, [task["id"]]) == 1
    (done,) = _ours(_rows(account, "tasks"))
    assert done["status"] == "done" and done["completed_at"] is not None
    assert _run("DELETE FROM tasks WHERE id = $1", account, [task["id"]]) == 1
    assert not [r for r in _ours(_rows(account, "tasks")) if not r["is_deleted"]]
