# Copyright (c) 2026 Kenneth Stott
# Canary: 6e2a9d13-4b7f-4c85-a1d0-8f3b5e7c9a26
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The calendar and task tables of a Google Workspace source (REQ-1994).

Each table is read whole, for every account of the source, at each refresh: ``calendars`` from
the account's calendar list; ``events`` and ``event_attendees`` from each calendar's events --
single events, series masters and exceptions, never the expanded occurrences of a series;
``task_lists`` and ``tasks`` from the account's task lists. A refresh is asked for when the
source's change token (:func:`change_token`) differs from the one its last read saw.

An account Google will not let be read at all (no such user, the service not turned on) is left
out and named on the build, as a mailbox is; anything else Google refuses fails the read.
"""

# Requirements: REQ-1994
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from provisa.core import canonical_mail as cm
from provisa.google_workspace import calendar_rows as rows
from provisa.google_workspace.workspace_api import WorkspaceApi

CALENDAR_TABLES = cm.RESOURCE_TABLES[cm.CALENDAR]
TASK_TABLES = cm.RESOURCE_TABLES[cm.TASKS]


def _live(item: dict) -> bool:
    """Whether an event Google listed is a row. Google answers ``cancelled`` for an event
    deleted outright and for a cancelled occurrence of a live series; only the second is a row
    (the event is still on the calendar, as an exception that cancels one occurrence)."""
    return item.get("status") != "cancelled" or bool(item.get("recurringEventId"))


async def account_rows(api: WorkspaceApi, table: str) -> AsyncIterator[list[dict]]:
    """The rows of one calendar or task table for one account, in batches."""
    account = api.account
    if table == "calendars":
        yield [rows.calendar_row(account, item) for item in await api.calendars()]
        return
    if table in ("events", "event_attendees"):
        for calendar in await api.calendars():
            async for page in api.events(calendar["id"]):
                batch: list[dict] = []
                for item in page:
                    if not _live(item):
                        continue
                    event, people = rows.event_rows(account, calendar["id"], item)
                    batch.extend([event] if table == "events" else people)
                if batch:
                    yield batch
        return
    if table == "task_lists":
        yield [rows.task_list_row(account, item) for item in await api.task_lists()]
        return
    if table == "tasks":
        for task_list in await api.task_lists():
            async for page in api.tasks(task_list["id"]):
                if page:
                    yield [rows.task_row(account, task_list["id"], item) for item in page]
        return
    raise LookupError(f"{table!r} is not a calendar or task table")


async def _accounts(reading: Any, each: Callable[[WorkspaceApi], Any], left_out: list[str]):
    """``each`` for every account of ``reading``, ``at_once`` at a time, their results in
    account order. An account Google will not let be read at all is added to ``left_out``."""
    from provisa.google_workspace.loader import NoMailboxRead, _not_readable

    gate = asyncio.Semaphore(max(reading.at_once, 1))
    refusals: list[str] = []
    async with httpx.AsyncClient() as client:

        async def one(account: str) -> Any:
            async def token() -> str:
                return await reading.token(account)

            api = WorkspaceApi(
                account,
                token,
                client,
                quota_user=reading.organisation,
                wait_seconds=reading.wait_seconds,
            )
            async with gate:
                try:
                    return await each(api)
                except Exception as refused:  # allow-ble: only an account Google will not let be read at all is taken here; every other failure is re-raised unchanged
                    why = _not_readable(refused) if reading.organisation else None
                    if why is None:
                        raise
                    left_out.append(account)
                    refusals.append(why)
                    return None

        results = await asyncio.gather(*(one(account) for account in reading.accounts))
    if reading.accounts and len(left_out) == len(reading.accounts):
        raise NoMailboxRead(len(reading.accounts), refusals[-1])
    return [r for r in results if r is not None]


async def table_rows(reading: Any, table: str, left_out: list[str]) -> list[list[dict]]:
    """Every account's rows of ``table``, in batches."""

    async def each(api: WorkspaceApi) -> list[list[dict]]:
        return [batch async for batch in account_rows(api, table)]

    return [batch for batches in await _accounts(reading, each, left_out) for batch in batches]


async def change_token(reading: Any, table: str) -> str:
    """The source's calendars, or its task lists, as they stand now, as one opaque token: an
    equal token is nothing changed. Calendars: each calendar list entry's tag and the time
    anything of each calendar last changed. Tasks: each list's tag and each task's id and
    update time."""

    async def calendars(api: WorkspaceApi) -> list[str]:
        lines = []
        for calendar in await api.calendars():
            updated = await api.calendar_updated(calendar["id"])
            lines.append(
                f"{api.account}\x00{calendar['id']}\x00{calendar.get('etag')}\x00{updated}"
            )
        return lines

    async def tasks(api: WorkspaceApi) -> list[str]:
        lines = []
        for task_list in await api.task_lists():
            lines.append(f"{api.account}\x00{task_list['id']}\x00{task_list.get('etag')}")
            async for page in api.tasks(task_list["id"]):
                lines.extend(
                    f"{api.account}\x00{task_list['id']}\x00{t['id']}\x00{t.get('updated')}"
                    for t in page
                )
        return lines

    each = calendars if table in CALENDAR_TABLES else tasks
    left_out: list[str] = []
    found = await _accounts(reading, each, left_out)
    lines = [line for part in found for line in part] + [f"{a}\x00left_out" for a in left_out]
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
