# Copyright (c) 2026 Kenneth Stott
# Canary: 4e7b0d58-6a2c-4f19-8c3e-d5a1b9f2c740
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Writes to a Microsoft 365 source's events, attendees and To Do tasks (REQ-1994).

A row written is turned into the Graph call that makes it so, as the mailbox the row names.

Graph has no way to change a meeting without telling its attendees: a change to the attendees,
or a change the organizer makes to a meeting that has any, is sent to them. Such a write is made
only when the source says to tell them (``calendar_send_updates``) and is refused by name
otherwise; a reminder of one's own is changed either way, as nobody is told of it.
"""

# Requirements: REQ-1994
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from provisa.federation.mail_write import Found, WriteRefused, as_date, as_instant
from provisa.microsoft365 import calendar as cal
from provisa.microsoft365.graph import Graph, GraphRefused, not_there
from provisa.microsoft365.recurrence import RecurrenceRefused, from_rfc5545

_SHOW_AS = {
    "free": "free",
    "busy": "busy",
    "tentative": "tentative",
    "out_of_office": "oof",
    "working_elsewhere": "workingElsewhere",
    "unknown": "unknown",
}
_SENSITIVITY = {
    "default": "normal",
    "personal": "personal",
    "private": "private",
    "confidential": "confidential",
}
_TASK_STATUS = {"open": "notStarted", "done": "completed"}
_IMPORTANCE = {v: v for v in ("low", "normal", "high")}
#: What a write may change on a meeting without anyone being told: the mailbox's own reminder.
_OWN = frozenset({"is_reminder_on", "reminder_minutes_before_start"})


def _q(part: str) -> str:
    return quote(part, safe="")


def _mapped(column: str, value: Any, table: dict[str, str]) -> str:
    if value not in table:
        raise WriteRefused(
            f"{column} {value!r} is not one Microsoft keeps; it keeps {', '.join(sorted(table))}"
        )
    return table[value]


def _wall(moment: dt.datetime, zone: str | None) -> dict[str, str]:
    """``moment`` as Graph takes a ``dateTimeTimeZone``: the wall time in ``zone`` (an IANA
    name), or in UTC where no zone is stated."""
    if zone is None or zone == "UTC":
        return {
            "dateTime": moment.astimezone(dt.UTC).replace(tzinfo=None).isoformat(),
            "timeZone": "UTC",
        }
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except ZoneInfoNotFoundError:
        raise WriteRefused(
            f"time zone {zone!r}: name it as an IANA zone (Europe/London), or leave it unstated "
            "for UTC"
        ) from None
    return {"dateTime": local.replace(tzinfo=None).isoformat(), "timeZone": zone}


@dataclass
class GraphWriter:
    """The writes of one mailbox. ``send_updates`` is the source's ``calendar_send_updates``."""

    graph: Graph
    account: str
    send_updates: bool

    @property
    def _root(self) -> str:
        return f"/users/{_q(self.account)}"

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict | None:
        try:
            return await asyncio.to_thread(self.graph.get, path, params, prefer=cal.PREFER)
        except GraphRefused as refused:
            if refused.status == 404 or not_there(refused):
                return None
            raise

    async def _write(self, method: str, path: str, body: Any = None) -> Any:
        return await asyncio.to_thread(self.graph.write, method, path, body, prefer=cal.PREFER)

    def _told(self, what: str) -> None:
        if not self.send_updates:
            raise WriteRefused(
                f"{what}: Microsoft tells the attendees of such a change, and this source tells "
                "nobody. Turn on its setting to tell attendees of a change, or make the change "
                "in Outlook"
            )

    def _meeting(self, item: dict) -> bool:
        """Whether the mailbox organizes ``item`` with anyone else attending."""
        others = [
            a
            for a in item.get("attendees") or []
            if ((a.get("emailAddress") or {}).get("address") or "").lower() != self.account.lower()
        ]
        return bool(item.get("isOrganizer")) and bool(others)

    # -- finding the rows a statement names -------------------------------------------------

    async def _event(self, event_id: str) -> tuple[str, dict] | None:
        item = await self._get(
            f"{self._root}/events/{_q(event_id)}",
            {"$select": cal.EVENT_FIELDS, "$expand": "calendar($select=id)"},
        )
        if item is None:
            return None
        return (item.get("calendar") or {}).get("id", ""), item

    async def _occurrence(self, series_id: str, start: Any) -> tuple[str, dict] | None:
        moment = as_instant(start)
        assert moment is not None
        master = await self._event(series_id)
        if master is None:
            return None
        page = await self._get(
            f"{self._root}/events/{_q(series_id)}/instances",
            {
                "startDateTime": (moment - dt.timedelta(days=1)).isoformat(),
                "endDateTime": (moment + dt.timedelta(days=1)).isoformat(),
                "$select": cal.EVENT_FIELDS,
            },
        )
        for item in (page or {}).get("value", []):
            if cal.instant(item.get("originalStart")) == moment:
                return master[0], item
        return None

    async def find_events(self, pins: dict[str, Any]) -> list[Found]:
        if pins.get("id") is not None:
            got = await self._event(pins["id"])
        elif pins.get("series_id") is not None and pins.get("original_start_at") is not None:
            got = await self._occurrence(pins["series_id"], pins["original_start_at"])
        else:
            raise WriteRefused(
                "a write to events names its event by id, or one occurrence of a series by "
                "series_id and original_start_at"
            )
        if got is None:
            return []
        calendar_id, item = got
        event, _people = cal.event_rows(self.account, calendar_id, item)
        return [Found(event, (calendar_id, item))]

    async def find_attendees(self, pins: dict[str, Any]) -> list[Found]:
        if pins.get("event_id") is None:
            raise WriteRefused("a write to event_attendees names its event by event_id")
        found: list[Found] = []
        for event in await self.find_events({"id": pins["event_id"]}):
            calendar_id, item = event.handle
            _event, people = cal.event_rows(self.account, calendar_id, item)
            found.extend(Found(p, (calendar_id, item, p["address"])) for p in people)
        return found

    async def find_tasks(self, pins: dict[str, Any]) -> list[Found]:
        if pins.get("id") is None:
            raise WriteRefused("a write to tasks names its task by id")
        if pins.get("task_list_id") is not None:
            lists = [pins["task_list_id"]]
        else:
            page = await self._get(f"{self._root}/todo/lists")
            lists = [item["id"] for item in (page or {}).get("value", [])]
        for list_id in lists:
            item = await self._get(f"{self._root}/todo/lists/{_q(list_id)}/tasks/{_q(pins['id'])}")
            if item is not None:
                return [Found(cal.task_row(self.account, list_id, item), (list_id, item))]
        return []

    # -- events ------------------------------------------------------------------------------

    def _event_body(self, values: dict[str, Any], current: dict | None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if "title" in values:
            body["subject"] = values["title"]
        if "body" in values:
            body["body"] = {"contentType": "text", "content": values["body"] or ""}
        if "location" in values:
            body["location"] = {"displayName": values["location"] or ""}
        if "show_as" in values:
            body["showAs"] = _mapped("show_as", values["show_as"], _SHOW_AS)
        if "visibility" in values:
            body["sensitivity"] = _mapped("visibility", values["visibility"], _SENSITIVITY)
        if "is_reminder_on" in values:
            body["isReminderOn"] = values["is_reminder_on"]
        if "reminder_minutes_before_start" in values:
            body["reminderMinutesBeforeStart"] = values["reminder_minutes_before_start"]
        times = {"is_all_day", "start_at", "end_at", "start_date", "end_date"}
        times |= {"start_time_zone", "end_time_zone"}
        if times & set(values):
            body.update(_times(values, current))
        if "recurrence" in values:
            body["recurrence"] = self._recurrence(values, current, body)
        return body

    def _recurrence(self, values: dict[str, Any], current: dict | None, body: dict) -> Any:
        text = values["recurrence"]
        if text is None:
            return None
        start = (body.get("start") or (current or {}).get("start") or {}).get("dateTime")
        if start is None:
            raise WriteRefused("a recurring event states when it starts")
        zone = (body.get("start") or {}).get("timeZone") or "UTC"
        try:
            return from_rfc5545(text, dt.date.fromisoformat(start[:10]), zone)
        except RecurrenceRefused as refused:
            raise WriteRefused(str(refused)) from None

    async def insert_event(self, values: dict[str, Any]) -> None:
        calendar_id = values.get("calendar_id")
        if not calendar_id:
            raise WriteRefused("an event is inserted into a calendar: name its calendar_id")
        await self._write(
            "POST",
            f"{self._root}/calendars/{_q(calendar_id)}/events",
            self._event_body(values, None),
        )

    async def update_event(self, handle: Any, values: dict[str, Any]) -> None:
        calendar_id, item = handle
        if "calendar_id" in values and values["calendar_id"] != calendar_id:
            raise WriteRefused("an event is not moved to another calendar by a write")
        if "recurrence" in values and item.get("type") in ("occurrence", "exception"):
            raise WriteRefused(
                "recurrence is set on a series, not on one occurrence: write the series row"
            )
        if self._meeting(item) and set(values) - _OWN:
            self._told("a change to a meeting with attendees")
        await self._write(
            "PATCH", f"{self._root}/events/{_q(item['id'])}", self._event_body(values, item)
        )

    async def delete_event(self, handle: Any) -> None:
        _calendar_id, item = handle
        if self._meeting(item):
            self._told("removing a meeting with attendees")
        await self._write("DELETE", f"{self._root}/events/{_q(item['id'])}")

    # -- attendees ---------------------------------------------------------------------------

    async def _set_attendees(self, item: dict, attendees: list[dict]) -> None:
        self._told("a change to an event's attendees")
        await self._write(
            "PATCH", f"{self._root}/events/{_q(item['id'])}", {"attendees": attendees}
        )

    async def insert_attendee(self, values: dict[str, Any]) -> None:
        if not values.get("event_id") or not values.get("address"):
            raise WriteRefused("an attendee is added to an event: name its event_id and address")
        got = await self._event(values["event_id"])
        if got is None:
            raise WriteRefused(f"there is no event {values['event_id']!r} to add an attendee to")
        _calendar_id, item = got
        attendees = list(item.get("attendees") or [])
        if any(
            ((a.get("emailAddress") or {}).get("address") or "").lower()
            == values["address"].lower()
            for a in attendees
        ):
            raise WriteRefused(f"{values['address']} already attends this event")
        attendees.append(
            _attendee({"emailAddress": {"address": values["address"]}, "type": "required"}, values)
        )
        await self._set_attendees(item, attendees)

    async def update_attendee(self, handle: Any, values: dict[str, Any]) -> None:
        _calendar_id, item, address = handle
        if "address" in values and values["address"] != address:
            raise WriteRefused("an attendee's address is not changed: remove it and add another")
        attendees = [
            _attendee(a, values) if (a.get("emailAddress") or {}).get("address") == address else a
            for a in item.get("attendees") or []
        ]
        await self._set_attendees(item, attendees)

    async def delete_attendee(self, handle: Any) -> None:
        _calendar_id, item, address = handle
        attendees = [
            a
            for a in item.get("attendees") or []
            if (a.get("emailAddress") or {}).get("address") != address
        ]
        await self._set_attendees(item, attendees)

    # -- tasks -------------------------------------------------------------------------------

    def _task_body(self, values: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if "title" in values:
            body["title"] = values["title"]
        if "notes" in values:
            body["body"] = {"contentType": "text", "content": values["notes"] or ""}
        if "status" in values:
            body["status"] = _mapped("status", values["status"], _TASK_STATUS)
        if "importance" in values:
            body["importance"] = _mapped("importance", values["importance"], _IMPORTANCE)
        if "due_at" in values or "due_date" in values:
            if "due_at" in values:
                due = as_instant(values["due_at"])
            else:
                day = as_date(values["due_date"])
                due = (
                    None
                    if day is None
                    else dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
                )
            body["dueDateTime"] = None if due is None else _wall(due, None)
        if "completed_at" in values:
            done = as_instant(values["completed_at"])
            body["completedDateTime"] = None if done is None else _wall(done, None)
        if "reminder_at" in values:
            at = as_instant(values["reminder_at"])
            body["reminderDateTime"] = None if at is None else _wall(at, None)
            if at is not None and "is_reminder_on" not in values:
                body["isReminderOn"] = True
        if "is_reminder_on" in values:
            body["isReminderOn"] = values["is_reminder_on"]
        return body

    async def insert_task(self, values: dict[str, Any]) -> None:
        list_id = values.get("task_list_id")
        if not list_id:
            raise WriteRefused("a task is inserted into a task list: name its task_list_id")
        await self._write(
            "POST", f"{self._root}/todo/lists/{_q(list_id)}/tasks", self._task_body(values)
        )

    async def update_task(self, handle: Any, values: dict[str, Any]) -> None:
        list_id, item = handle
        if "task_list_id" in values and values["task_list_id"] != list_id:
            raise WriteRefused("a task is not moved to another list by a write")
        await self._write(
            "PATCH",
            f"{self._root}/todo/lists/{_q(list_id)}/tasks/{_q(item['id'])}",
            self._task_body(values),
        )

    async def delete_task(self, handle: Any) -> None:
        list_id, item = handle
        await self._write("DELETE", f"{self._root}/todo/lists/{_q(list_id)}/tasks/{_q(item['id'])}")


def _attendee(attendee: dict, values: dict[str, Any]) -> dict:
    out = {**attendee, "emailAddress": dict(attendee.get("emailAddress") or {})}
    out.pop("status", None)
    if "name" in values:
        out["emailAddress"]["name"] = values["name"]
    if "kind" in values:
        kind = values["kind"]
        if kind not in ("required", "optional", "resource"):
            raise WriteRefused(f"kind {kind!r}: an attendee is required, optional or a resource")
        out["type"] = kind
    return out


def _times(values: dict[str, Any], current: dict | None) -> dict[str, Any]:
    """An event's start and end as Graph takes them, from what the write sets over what the
    event has now."""
    now = current or {}
    all_day = values.get("is_all_day", bool(now.get("isAllDay", False)))
    if all_day:
        start = as_date(values["start_date"]) if "start_date" in values else _day(now.get("start"))
        end = as_date(values["end_date"]) if "end_date" in values else _day(now.get("end"))
        if start is None or end is None:
            raise WriteRefused("an all-day event states its start_date and end_date")
        return {
            "isAllDay": True,
            "start": {"dateTime": f"{start.isoformat()}T00:00:00", "timeZone": "UTC"},
            "end": {"dateTime": f"{end.isoformat()}T00:00:00", "timeZone": "UTC"},
        }
    start = (
        as_instant(values["start_at"]) if "start_at" in values else cal.instant(now.get("start"))
    )
    end = as_instant(values["end_at"]) if "end_at" in values else cal.instant(now.get("end"))
    if start is None or end is None:
        raise WriteRefused("an event states its start_at and end_at, or is all-day")
    start_zone = values.get("start_time_zone")
    end_zone = values.get("end_time_zone", start_zone)
    return {"isAllDay": False, "start": _wall(start, start_zone), "end": _wall(end, end_zone)}


def _day(moment: dict | None) -> dt.date | None:
    at = cal.instant(moment)
    return None if at is None else at.date()
