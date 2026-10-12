# Copyright (c) 2026 Kenneth Stott
# Canary: 8a3f6c12-9d4e-4b70-a5e1-0c2d7b9e4f63
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The calendar and task tables of a Microsoft 365 source (REQ-1994).

Each table is read whole, for every mailbox of the source, at each refresh, from Microsoft
Graph: ``calendars`` from the mailbox's calendars; ``events`` and ``event_attendees`` from each
calendar's ``/events`` -- single events and series masters -- and each series master's
exceptions (``exceptionOccurrences``), never the expanded occurrences of a series;
``task_lists`` and ``tasks`` from Microsoft To Do.

Whether anything changed is asked without reading the tables (:func:`change_token`): each
calendar's events in a window around today (``calendar_check_days`` either side, a setting of
the source) by id and change key, and each task's id and update time.

Graph answers times in UTC (it is never asked for another zone); a zone the item was made in is
kept beside its time (``start_time_zone``).
"""

# Requirements: REQ-1994
from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from provisa.core import canonical_mail as cm
from provisa.microsoft365.graph import Graph
from provisa.microsoft365.recurrence import to_rfc5545

PROVIDER = cm.MICROSOFT
#: Times in UTC, and a task's notes as text (Graph's own body-content preference).
PREFER = ('outlook.timezone="UTC"', 'outlook.body-content-type="text"')
EVENT_FIELDS = (
    "id,iCalUId,subject,bodyPreview,body,location,locations,isAllDay,start,end,"
    "originalStartTimeZone,originalEndTimeZone,isCancelled,showAs,sensitivity,importance,type,"
    "seriesMasterId,originalStart,recurrence,organizer,isOrganizer,attendees,isOnlineMeeting,"
    "onlineMeeting,onlineMeetingProvider,hasAttachments,categories,createdDateTime,"
    "lastModifiedDateTime,changeKey,webLink,isReminderOn,reminderMinutesBeforeStart,isDraft,"
    "responseRequested,allowNewTimeProposals,responseStatus,hideAttendees,cancelledOccurrences"
)


class UnexpectedAnswer(RuntimeError):
    """Graph answered something this reader does not read."""


def _q(part: str) -> str:
    return quote(part, safe="")


def row(table: str, account: str, **values: Any) -> dict[str, Any]:
    """A row of ``table``: every canonical column in order, None where no value is given."""
    columns = cm.TABLES[table].columns
    known = {c.name: c for c in columns}
    for name in values:
        if name not in known:
            raise KeyError(f"{table} has no column {name!r}")
        if not known[name].populated_by(PROVIDER):
            raise KeyError(f"{table}.{name} is not a column Microsoft populates")
    out: dict[str, Any] = {c.name: values.get(c.name) for c in columns}
    out["provider"] = PROVIDER
    out["account"] = account
    return out


def instant(moment: dict | str | None) -> dt.datetime | None:
    """A Graph ``dateTimeTimeZone`` (asked for in UTC) or a ``DateTimeOffset``, in UTC."""
    if moment is None:
        return None
    if isinstance(moment, dict):
        if moment.get("timeZone") not in ("UTC", "Etc/GMT", "tzone://Microsoft/Utc"):
            raise UnexpectedAnswer(
                f"Graph answered a time in the zone {moment.get('timeZone')!r}; UTC was asked for"
            )
        text = moment["dateTime"]
    else:
        text = moment
    whole, dot, fraction = text.replace("Z", "").partition(".")
    parsed = dt.datetime.fromisoformat(f"{whole}{dot}{fraction[:6]}" if dot else whole)
    if "+" in whole[10:] or parsed.tzinfo is not None:
        return parsed.astimezone(dt.UTC)
    return parsed.replace(tzinfo=dt.UTC)


def _address(holder: dict | None) -> tuple[str | None, str | None]:
    email = (holder or {}).get("emailAddress") or {}
    return email.get("address"), email.get("name")


def calendar_row(account: str, item: dict) -> dict[str, Any]:
    owner = (item.get("owner") or {}).get("address")
    return row(
        "calendars",
        account,
        id=item["id"],
        name=item.get("name"),
        is_primary=bool(item.get("isDefaultCalendar", False)),
        can_edit=item.get("canEdit"),
        owner_address=owner,
        color=item.get("hexColor") or None,
        change_key=item.get("changeKey"),
        can_share=item.get("canShare"),
        can_view_private_items=item.get("canViewPrivateItems"),
        is_removable=item.get("isRemovable"),
        default_online_meeting_provider=item.get("defaultOnlineMeetingProvider"),
        allowed_online_meeting_providers=item.get("allowedOnlineMeetingProviders"),
    )


def event_rows(account: str, calendar_id: str, item: dict) -> tuple[dict, list[dict]]:
    """The event's row and its attendees' rows."""
    all_day = bool(item.get("isAllDay", False))
    start, end = instant(item.get("start")), instant(item.get("end"))
    organizer, organizer_name = _address(item.get("organizer"))
    attendees = item.get("attendees") or []
    body = item.get("body") or {}
    online = item.get("onlineMeeting") or {}
    response = (item.get("responseStatus") or {}).get("response")
    event = row(
        "events",
        account,
        id=item["id"],
        calendar_id=calendar_id,
        ical_uid=item.get("iCalUId"),
        title=item.get("subject"),
        snippet=item.get("bodyPreview"),
        body=body.get("content"),
        body_format=cm.translate("body_format", PROVIDER, body.get("contentType")),
        location=(item.get("location") or {}).get("displayName") or None,
        is_all_day=all_day,
        start_at=None if all_day else start,
        end_at=None if all_day else end,
        start_date=start.date() if all_day and start else None,
        end_date=end.date() if all_day and end else None,
        start_time_zone=item.get("originalStartTimeZone"),
        end_time_zone=item.get("originalEndTimeZone"),
        status="cancelled" if item.get("isCancelled") else None,
        is_cancelled=bool(item.get("isCancelled", False)),
        show_as=cm.translate("show_as", PROVIDER, item.get("showAs")),
        visibility=cm.translate("event_visibility", PROVIDER, item.get("sensitivity")),
        importance=cm.translate("importance", PROVIDER, item.get("importance")),
        kind=cm.translate("event_kind", PROVIDER, item.get("type")),
        series_id=item.get("seriesMasterId"),
        original_start_at=instant(item.get("originalStart")),
        recurrence=to_rfc5545(item.get("recurrence")),
        organizer_address=organizer,
        organizer_name=organizer_name,
        is_organizer=item.get("isOrganizer"),
        attendee_addresses=[a for a in (_address(x)[0] for x in attendees) if a],
        is_online_meeting=item.get("isOnlineMeeting"),
        online_meeting_url=online.get("joinUrl"),
        has_attachments=item.get("hasAttachments"),
        categories=item.get("categories"),
        created_at=instant(item.get("createdDateTime")),
        updated_at=instant(item.get("lastModifiedDateTime")),
        change_key=item.get("changeKey"),
        web_link=item.get("webLink"),
        guests_can_see_other_guests=None
        if item.get("hideAttendees") is None
        else not item["hideAttendees"],
        is_reminder_on=item.get("isReminderOn"),
        reminder_minutes_before_start=item.get("reminderMinutesBeforeStart"),
        conference=item.get("onlineMeeting"),
        online_meeting_provider=item.get("onlineMeetingProvider"),
        locations=item.get("locations"),
        is_draft=item.get("isDraft"),
        is_response_requested=item.get("responseRequested"),
        allow_new_time_proposals=item.get("allowNewTimeProposals"),
        my_response=None
        if response is None
        else cm.translate("attendee_response", PROVIDER, response),
        cancelled_occurrences=item.get("cancelledOccurrences"),
    )
    people = []
    for position, attendee in enumerate(attendees, 1):
        address, name = _address(attendee)
        status = attendee.get("status") or {}
        said = status.get("response")
        people.append(
            row(
                "event_attendees",
                account,
                event_id=item["id"],
                position=position,
                address=address,
                name=name,
                kind=cm.translate("attendee_kind", PROVIDER, attendee.get("type")),
                response=None
                if said is None
                else cm.translate("attendee_response", PROVIDER, said),
                responded_at=instant(status.get("time")),
                is_organizer=said == "organizer",
                is_self=(address or "").lower() == account.lower(),
            )
        )
    return event, people


def task_list_row(account: str, item: dict) -> dict[str, Any]:
    role = item.get("wellknownListName")
    return row(
        "task_lists",
        account,
        id=item["id"],
        name=item.get("displayName"),
        is_default=role == "defaultList",
        role=cm.translate("task_list_role", PROVIDER, role),
        is_shared=item.get("isShared"),
    )


def task_row(account: str, list_id: str, item: dict) -> dict[str, Any]:
    status = item.get("status")
    due = instant(item.get("dueDateTime"))
    return row(
        "tasks",
        account,
        id=item["id"],
        task_list_id=list_id,
        title=item.get("title"),
        notes=(item.get("body") or {}).get("content") or None,
        status=cm.translate("task_status", PROVIDER, status),
        vendor_status=status,
        importance=cm.translate("importance", PROVIDER, item.get("importance")),
        due_date=None if due is None else due.date(),
        due_at=due,
        start_at=instant(item.get("startDateTime")),
        completed_at=instant(item.get("completedDateTime")),
        reminder_at=instant(item.get("reminderDateTime")),
        recurrence=to_rfc5545(item.get("recurrence")),
        categories=item.get("categories"),
        has_attachments=item.get("hasAttachments"),
        created_at=instant(item.get("createdDateTime")),
        updated_at=instant(item.get("lastModifiedDateTime")),
        is_reminder_on=item.get("isReminderOn"),
        notes_updated_at=instant(item.get("bodyLastModifiedDateTime")),
    )


# -- reading ----------------------------------------------------------------------------------


def _items(graph: Graph, path: str, params: dict[str, str] | None = None) -> Iterator[dict]:
    for page in graph.pages(path, params, prefer=PREFER):
        yield from page


def calendars(graph: Graph, account: str) -> list[dict]:
    return list(_items(graph, f"/users/{_q(account)}/calendars"))


def _calendar_events(graph: Graph, account: str, calendar_id: str) -> Iterator[dict]:
    """The calendar's single events and series masters, and each master's exceptions."""
    base = f"/users/{_q(account)}/calendars/{_q(calendar_id)}/events"
    for item in _items(graph, base, {"$select": EVENT_FIELDS, "$top": "100"}):
        yield item
        if item.get("type") == "seriesMaster":
            master = graph.get(
                f"/users/{_q(account)}/events/{_q(item['id'])}",
                {"$select": "id", "$expand": f"exceptionOccurrences($select={EVENT_FIELDS})"},
                prefer=PREFER,
            )
            yield from master.get("exceptionOccurrences") or []


def account_rows(graph: Graph, account: str, table: str) -> Iterator[list[dict]]:
    """The rows of one calendar or task table for one mailbox, in batches."""
    if table == "calendars":
        yield [calendar_row(account, item) for item in calendars(graph, account)]
        return
    if table in ("events", "event_attendees"):
        for calendar in calendars(graph, account):
            batch: list[dict] = []
            for item in _calendar_events(graph, account, calendar["id"]):
                event, people = event_rows(account, calendar["id"], item)
                batch.extend([event] if table == "events" else people)
            if batch:
                yield batch
        return
    lists = list(_items(graph, f"/users/{_q(account)}/todo/lists"))
    if table == "task_lists":
        yield [task_list_row(account, item) for item in lists]
        return
    if table == "tasks":
        for task_list in lists:
            tasks = list(
                _items(graph, f"/users/{_q(account)}/todo/lists/{_q(task_list['id'])}/tasks")
            )
            if tasks:
                yield [task_row(account, task_list["id"], item) for item in tasks]
        return
    raise LookupError(f"{table!r} is not a calendar or task table")


def change_lines(graph: Graph, account: str, table: str, days: int) -> list[str]:
    """What the mailbox's calendars, or its task lists, are now, as lines a token is made of:
    each calendar's change key and its events in ``days`` either side of today by id and change
    key; each list's tasks by id and update time."""
    lines: list[str] = []
    if table in cm.RESOURCE_TABLES[cm.CALENDAR]:
        today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        window = {
            "startDateTime": (today - dt.timedelta(days=days)).isoformat(),
            "endDateTime": (today + dt.timedelta(days=days)).isoformat(),
            "$select": "id,changeKey",
            "$top": "500",
        }
        for calendar in calendars(graph, account):
            lines.append(f"{account}\x00{calendar['id']}\x00{calendar.get('changeKey')}")
            path = f"/users/{_q(account)}/calendars/{_q(calendar['id'])}/calendarView"
            lines.extend(
                f"{account}\x00{calendar['id']}\x00{e['id']}\x00{e.get('changeKey')}"
                for e in _items(graph, path, window)
            )
        return lines
    for task_list in _items(graph, f"/users/{_q(account)}/todo/lists"):
        lines.append(f"{account}\x00{task_list['id']}\x00{task_list.get('displayName')}")
        path = f"/users/{_q(account)}/todo/lists/{_q(task_list['id'])}/tasks"
        lines.extend(
            f"{account}\x00{task_list['id']}\x00{t['id']}\x00{t.get('lastModifiedDateTime')}"
            for t in _items(graph, path, {"$select": "id,lastModifiedDateTime"})
        )
    return lines


def token_of(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
