# Copyright (c) 2026 Kenneth Stott
# Canary: 0f5b7a2c-8e31-4d69-b4a7-c2e9d1f6038b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Writes to a Google Workspace source's events, attendees and tasks (REQ-1994).

A row written is turned into the Calendar or Tasks call that makes it so, as the account the
row names: an INSERT creates, an UPDATE patches what it sets, a DELETE removes. A change to an
event or its attendees tells the attendees only when the source says so
(``calendar_send_updates``). A single occurrence of a series is named by the series and the
occurrence's original start; changing or removing it makes it an exception of the series.

Google's Tasks API has no reminder and keeps only the day of a task's due time, so a task
write of those Microsoft-only columns is refused by name (``canonical_mail``: what Google
populates).
"""

# Requirements: REQ-1994
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from provisa.federation.mail_write import (
    Found,
    WriteRefused,
    as_date,
    as_instant,
    rfc3339,
)
from provisa.google_workspace import calendar_rows as rows
from provisa.google_workspace.gmail import GmailNotFound
from provisa.google_workspace.workspace_api import CALENDAR_URL, TASKS_URL, WorkspaceApi

_SHOW_AS = {"free": "transparent", "busy": "opaque"}
_VISIBILITY = {v: v for v in ("default", "public", "private", "confidential")}
_TASK_STATUS = {"open": "needsAction", "done": "completed"}


def _q(part: str) -> str:
    return quote(part, safe="")


@dataclass
class GoogleWriter:
    """The writes of one account. ``send_updates`` is the source's ``calendar_send_updates``."""

    api: WorkspaceApi
    send_updates: bool

    @property
    def _notify(self) -> dict[str, str]:
        return {"sendUpdates": "all" if self.send_updates else "none"}

    # -- finding the rows a statement names -------------------------------------------------

    async def _calendar_ids(self, pins: dict[str, Any]) -> list[str]:
        if pins.get("calendar_id") is not None:
            return [pins["calendar_id"]]
        return [c["id"] for c in await self.api.calendars()]

    async def _event(self, calendar_id: str, event_id: str) -> dict | None:
        try:
            return await self.api.call(
                "GET",
                CALENDAR_URL + f"calendars/{_q(calendar_id)}/events/{_q(event_id)}",
                call="events.get",
            )
        except GmailNotFound:
            return None

    async def _occurrence(self, calendar_id: str, series_id: str, start: Any) -> dict | None:
        """The occurrence of ``series_id`` that originally starts at ``start``: an exception
        already made of it, or the occurrence as the series gives it."""
        try:
            page = await self.api.call(
                "GET",
                CALENDAR_URL + f"calendars/{_q(calendar_id)}/events/{_q(series_id)}/instances",
                params={"originalStart": rfc3339(as_instant(start)), "showDeleted": "true"},
                call="events.instances",
            )
        except GmailNotFound:
            return None
        items = page.get("items", [])
        return items[0] if items else None

    async def find_events(self, pins: dict[str, Any]) -> list[Found]:
        found: list[Found] = []
        for calendar_id in await self._calendar_ids(pins):
            if pins.get("id") is not None:
                item = await self._event(calendar_id, pins["id"])
            elif pins.get("series_id") is not None and pins.get("original_start_at") is not None:
                item = await self._occurrence(
                    calendar_id, pins["series_id"], pins["original_start_at"]
                )
            else:
                raise WriteRefused(
                    "a write to events names its event by id, or one occurrence of a series "
                    "by series_id and original_start_at"
                )
            if item is None or item.get("status") == "cancelled":
                continue
            event, _people = rows.event_rows(self.api.account, calendar_id, item)
            found.append(Found(event, (calendar_id, item)))
            if pins.get("id") is not None:
                break  # an event id is one event, whichever calendar holds it
        return found

    async def find_attendees(self, pins: dict[str, Any]) -> list[Found]:
        if pins.get("event_id") is None:
            raise WriteRefused("a write to event_attendees names its event by event_id")
        found: list[Found] = []
        for event in await self.find_events({**pins, "id": pins["event_id"]}):
            calendar_id, item = event.handle
            _event, people = rows.event_rows(self.api.account, calendar_id, item)
            for person in people:
                found.append(Found(person, (calendar_id, item, person["address"])))
        return found

    async def _list_ids(self, pins: dict[str, Any]) -> list[str]:
        if pins.get("task_list_id") is not None:
            return [pins["task_list_id"]]
        return [t["id"] for t in await self.api.task_lists()]

    async def find_tasks(self, pins: dict[str, Any]) -> list[Found]:
        if pins.get("id") is None:
            raise WriteRefused("a write to tasks names its task by id")
        for list_id in await self._list_ids(pins):
            try:
                item = await self.api.call(
                    "GET",
                    TASKS_URL + f"lists/{_q(list_id)}/tasks/{_q(pins['id'])}",
                    call="tasks.get",
                )
            except GmailNotFound:
                continue
            if item.get("deleted"):
                continue
            return [Found(rows.task_row(self.api.account, list_id, item), (list_id, item))]
        return []

    # -- events ------------------------------------------------------------------------------

    def _event_body(self, values: dict[str, Any], current: dict | None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        simple = {"title": "summary", "body": "description", "location": "location"}
        for column, field in simple.items():
            if column in values:
                body[field] = values[column]
        times = {
            "is_all_day",
            "start_at",
            "end_at",
            "start_date",
            "end_date",
            "start_time_zone",
            "end_time_zone",
        }
        if times & set(values):
            body.update(_times(values, current))
        if "show_as" in values:
            body["transparency"] = _mapped("show_as", values["show_as"], _SHOW_AS)
        if "visibility" in values:
            body["visibility"] = _mapped("visibility", values["visibility"], _VISIBILITY)
        if "recurrence" in values:
            text = values["recurrence"]
            body["recurrence"] = (
                [] if text is None else [line for line in text.splitlines() if line]
            )
        if "reminders" in values:
            reminders = values["reminders"]
            body["reminders"] = json.loads(reminders) if isinstance(reminders, str) else reminders
        return body

    async def insert_event(self, values: dict[str, Any]) -> None:
        calendar_id = values.get("calendar_id")
        if not calendar_id:
            raise WriteRefused("an event is inserted into a calendar: name its calendar_id")
        await self.api.call(
            "POST",
            CALENDAR_URL + f"calendars/{_q(calendar_id)}/events",
            params=self._notify,
            body=self._event_body(values, None),
            call="events.insert",
        )

    async def update_event(self, handle: Any, values: dict[str, Any]) -> None:
        calendar_id, item = handle
        if "calendar_id" in values and values["calendar_id"] != calendar_id:
            raise WriteRefused("an event is not moved to another calendar by a write")
        if "recurrence" in values and item.get("recurringEventId"):
            raise WriteRefused(
                "recurrence is set on a series, not on one occurrence: write the series row"
            )
        await self.api.call(
            "PATCH",
            CALENDAR_URL + f"calendars/{_q(calendar_id)}/events/{_q(item['id'])}",
            params=self._notify,
            body=self._event_body(values, item),
            call="events.patch",
        )

    async def delete_event(self, handle: Any) -> None:
        calendar_id, item = handle
        await self.api.call(
            "DELETE",
            CALENDAR_URL + f"calendars/{_q(calendar_id)}/events/{_q(item['id'])}",
            params=self._notify,
            call="events.delete",
        )

    # -- attendees ---------------------------------------------------------------------------

    async def _set_attendees(self, calendar_id: str, item: dict, attendees: list[dict]) -> None:
        await self.api.call(
            "PATCH",
            CALENDAR_URL + f"calendars/{_q(calendar_id)}/events/{_q(item['id'])}",
            params=self._notify,
            body={"attendees": attendees},
            call="events.patch",
        )

    async def insert_attendee(self, values: dict[str, Any]) -> None:
        if not values.get("event_id") or not values.get("address"):
            raise WriteRefused("an attendee is added to an event: name its event_id and address")
        events = await self.find_events(
            {"id": values["event_id"], "calendar_id": values.get("calendar_id")}
        )
        if not events:
            raise WriteRefused(f"there is no event {values['event_id']!r} to add an attendee to")
        calendar_id, item = events[0].handle
        attendees = list(item.get("attendees") or [])
        if any(a.get("email", "").lower() == values["address"].lower() for a in attendees):
            raise WriteRefused(f"{values['address']} already attends this event")
        attendees.append(_attendee({"email": values["address"]}, values))
        await self._set_attendees(calendar_id, item, attendees)

    async def update_attendee(self, handle: Any, values: dict[str, Any]) -> None:
        calendar_id, item, address = handle
        if "address" in values and values["address"] != address:
            raise WriteRefused("an attendee's address is not changed: remove it and add another")
        attendees = [
            _attendee(a, values) if a.get("email") == address else a
            for a in item.get("attendees") or []
        ]
        await self._set_attendees(calendar_id, item, attendees)

    async def delete_attendee(self, handle: Any) -> None:
        calendar_id, item, address = handle
        attendees = [a for a in item.get("attendees") or [] if a.get("email") != address]
        await self._set_attendees(calendar_id, item, attendees)

    # -- tasks -------------------------------------------------------------------------------

    def _task_body(self, values: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if "title" in values:
            body["title"] = values["title"]
        if "notes" in values:
            body["notes"] = values["notes"]
        if "status" in values:
            body["status"] = _mapped("status", values["status"], _TASK_STATUS)
        if "due_date" in values:
            due = as_date(values["due_date"])
            body["due"] = None if due is None else f"{due.isoformat()}T00:00:00.000Z"
        if "completed_at" in values:
            body["completed"] = rfc3339(as_instant(values["completed_at"]))
        return body

    async def insert_task(self, values: dict[str, Any]) -> None:
        list_id = values.get("task_list_id")
        if not list_id:
            raise WriteRefused("a task is inserted into a task list: name its task_list_id")
        await self.api.call(
            "POST",
            TASKS_URL + f"lists/{_q(list_id)}/tasks",
            body=self._task_body(values),
            call="tasks.insert",
        )

    async def update_task(self, handle: Any, values: dict[str, Any]) -> None:
        list_id, item = handle
        if "task_list_id" in values and values["task_list_id"] != list_id:
            raise WriteRefused("a task is not moved to another list by a write")
        await self.api.call(
            "PATCH",
            TASKS_URL + f"lists/{_q(list_id)}/tasks/{_q(item['id'])}",
            body=self._task_body(values),
            call="tasks.patch",
        )

    async def delete_task(self, handle: Any) -> None:
        list_id, item = handle
        await self.api.call(
            "DELETE", TASKS_URL + f"lists/{_q(list_id)}/tasks/{_q(item['id'])}", call="tasks.delete"
        )


def _mapped(column: str, value: Any, table: dict[str, str]) -> str:
    if value not in table:
        raise WriteRefused(
            f"{column} {value!r} is not one Google keeps; it keeps {', '.join(sorted(table))}"
        )
    return table[value]


def _attendee(attendee: dict, values: dict[str, Any]) -> dict:
    out = dict(attendee)
    if "name" in values:
        out["displayName"] = values["name"]
    if "kind" in values:
        kind = values["kind"]
        if kind not in ("required", "optional"):
            raise WriteRefused(
                f"kind {kind!r}: an attendee is added as required or optional; a resource is "
                "booked through the room's own calendar"
            )
        out["optional"] = kind == "optional"
    return out


def _times(values: dict[str, Any], current: dict | None) -> dict[str, Any]:
    """An event's start and end as Google takes them, from what the write sets over what the
    event has now."""
    now_start, now_end = (current or {}).get("start") or {}, (current or {}).get("end") or {}
    all_day = values.get("is_all_day", "date" in now_start)
    if all_day:
        start = as_date(values["start_date"]) if "start_date" in values else now_start.get("date")
        end = as_date(values["end_date"]) if "end_date" in values else now_end.get("date")
        if start is None or end is None:
            raise WriteRefused("an all-day event states its start_date and end_date")
        return {"start": {"date": str(start)}, "end": {"date": str(end)}}
    start_zone = values.get("start_time_zone", now_start.get("timeZone"))
    end_zone = values.get("end_time_zone", now_end.get("timeZone"))
    start = (
        rfc3339(as_instant(values["start_at"]))
        if "start_at" in values
        else now_start.get("dateTime")
    )
    end = rfc3339(as_instant(values["end_at"])) if "end_at" in values else now_end.get("dateTime")
    if start is None or end is None:
        raise WriteRefused("an event states its start_at and end_at, or is all-day")
    return {
        "start": {"dateTime": start, **({"timeZone": start_zone} if start_zone else {})},
        "end": {"dateTime": end, **({"timeZone": end_zone} if end_zone else {})},
    }
