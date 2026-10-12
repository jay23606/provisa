# Copyright (c) 2026 Kenneth Stott
# Canary: 9c4d2e71-1a8b-4f30-b6e5-3d7f0a9c2b14
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Google Calendar and Tasks items as rows of the canonical tables (REQ-1994).

Each function takes what Google answered for one item and gives its row (or rows) with exactly
the canonical columns (``provisa.core.canonical_mail``), every enumeration value translated.
A column Google has no value for is None; a column Google does not populate is never set.
"""

# Requirements: REQ-1994
from __future__ import annotations

import datetime as dt
from typing import Any

from provisa.core import canonical_mail as cm

PROVIDER = cm.GOOGLE
_EDITING_ROLES = frozenset({"owner", "writer", "writerWithoutPrivateAccess"})


def row(table: str, account: str, **values: Any) -> dict[str, Any]:
    """A row of ``table``: every canonical column in order, None where no value is given. A
    value for a column the table does not have, or one Google does not populate, is an error of
    this module, raised here."""
    columns = cm.TABLES[table].columns
    known = {c.name: c for c in columns}
    for name in values:
        if name not in known:
            raise KeyError(f"{table} has no column {name!r}")
        if not known[name].populated_by(PROVIDER):
            raise KeyError(f"{table}.{name} is not a column Google populates")
    out: dict[str, Any] = {c.name: values.get(c.name) for c in columns}
    out["provider"] = PROVIDER
    out["account"] = account
    return out


def instant(value: str | None) -> dt.datetime | None:
    """An RFC 3339 time as Google writes it, in UTC."""
    if value is None:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)


def day(value: str | None) -> dt.date | None:
    return None if value is None else dt.date.fromisoformat(value[:10])


def calendar_row(account: str, item: dict) -> dict[str, Any]:
    role = item.get("accessRole")
    return row(
        "calendars",
        account,
        id=item["id"],
        name=item.get("summary"),
        description=item.get("description"),
        time_zone=item.get("timeZone"),
        is_primary=bool(item.get("primary", False)),
        can_edit=role in _EDITING_ROLES,
        access_role=cm.translate("calendar_access_role", PROVIDER, role),
        owner_address=None if item.get("primary") else item.get("dataOwner"),
        color=item.get("backgroundColor"),
        change_key=item.get("etag"),
        name_override=item.get("summaryOverride"),
        is_hidden=item.get("hidden"),
        is_selected=item.get("selected"),
        location=item.get("location"),
        color_text=item.get("foregroundColor"),
    )


def _kind(item: dict) -> str:
    if item.get("recurrence"):
        return "series_master"
    if item.get("recurringEventId"):
        return "exception"
    return "single"


def _attendee_kind(attendee: dict) -> str:
    if attendee.get("resource"):
        return "resource"
    if attendee.get("optional"):
        return "optional"
    return "required"


def event_rows(account: str, calendar_id: str, item: dict) -> tuple[dict, list[dict]]:
    """The event's row and its attendees' rows."""
    start, end = item.get("start") or {}, item.get("end") or {}
    all_day = "date" in start
    attendees = item.get("attendees") or []
    me = next((a for a in attendees if a.get("self")), None)
    original = item.get("originalStartTime") or {}
    organizer = item.get("organizer") or {}
    creator = item.get("creator") or {}
    event = row(
        "events",
        account,
        id=item["id"],
        calendar_id=calendar_id,
        ical_uid=item.get("iCalUID"),
        title=item.get("summary"),
        body=item.get("description"),
        location=item.get("location"),
        is_all_day=all_day,
        start_at=None if all_day else instant(start.get("dateTime")),
        end_at=None if all_day else instant(end.get("dateTime")),
        start_date=day(start.get("date")) if all_day else None,
        end_date=day(end.get("date")) if all_day else None,
        start_time_zone=start.get("timeZone"),
        end_time_zone=end.get("timeZone"),
        status=cm.translate("event_status", PROVIDER, item.get("status")),
        is_cancelled=item.get("status") == "cancelled",
        show_as=cm.translate("show_as", PROVIDER, item.get("transparency", "opaque")),
        visibility=cm.translate("event_visibility", PROVIDER, item.get("visibility", "default")),
        kind=cm.canonical("event_kind", _kind(item)),
        series_id=item.get("recurringEventId"),
        original_start_at=instant(original.get("dateTime")),
        recurrence="\n".join(item["recurrence"]) if item.get("recurrence") else None,
        organizer_address=organizer.get("email"),
        organizer_name=organizer.get("displayName"),
        is_organizer=bool(organizer.get("self", False)),
        attendee_addresses=[a["email"] for a in attendees if a.get("email")],
        is_online_meeting=bool(item.get("hangoutLink") or item.get("conferenceData")),
        online_meeting_url=item.get("hangoutLink"),
        has_attachments=bool(item.get("attachments")),
        created_at=instant(item.get("created")),
        updated_at=instant(item.get("updated")),
        change_key=item.get("etag"),
        web_link=item.get("htmlLink"),
        original_start_date=day(original.get("date")),
        creator_address=creator.get("email"),
        creator_name=creator.get("displayName"),
        event_type=cm.translate("event_type", PROVIDER, item.get("eventType")),
        sequence=item.get("sequence"),
        is_end_unspecified=item.get("endTimeUnspecified"),
        guests_can_modify=item.get("guestsCanModify"),
        guests_can_invite_others=item.get("guestsCanInviteOthers"),
        guests_can_see_other_guests=item.get("guestsCanSeeOtherGuests"),
        reminders=item.get("reminders"),
        conference=item.get("conferenceData"),
        attachments=item.get("attachments"),
        color_id=item.get("colorId"),
        my_response=None
        if me is None
        else cm.translate("attendee_response", PROVIDER, me.get("responseStatus")),
    )
    people = [
        row(
            "event_attendees",
            account,
            event_id=item["id"],
            position=position,
            address=attendee.get("email"),
            name=attendee.get("displayName"),
            kind=cm.canonical("attendee_kind", _attendee_kind(attendee)),
            response=cm.translate("attendee_response", PROVIDER, attendee.get("responseStatus")),
            is_organizer=bool(attendee.get("organizer", False)),
            comment=attendee.get("comment"),
            additional_guests=attendee.get("additionalGuests"),
            is_self=bool(attendee.get("self", False)),
        )
        for position, attendee in enumerate(attendees, 1)
    ]
    return event, people


def task_list_row(account: str, item: dict) -> dict[str, Any]:
    return row(
        "task_lists",
        account,
        id=item["id"],
        name=item.get("title"),
        updated_at=instant(item.get("updated")),
        change_key=item.get("etag"),
    )


def task_row(account: str, list_id: str, item: dict) -> dict[str, Any]:
    status = item.get("status")
    return row(
        "tasks",
        account,
        id=item["id"],
        task_list_id=list_id,
        parent_id=item.get("parent"),
        position=item.get("position"),
        title=item.get("title"),
        notes=item.get("notes"),
        status=cm.translate("task_status", PROVIDER, status),
        vendor_status=status,
        # Google keeps the day of a task's due time and drops the time.
        due_date=day(item.get("due")),
        completed_at=instant(item.get("completed")),
        is_deleted=item.get("deleted"),
        is_hidden=item.get("hidden"),
        updated_at=instant(item.get("updated")),
        web_link=item.get("webViewLink"),
        change_key=item.get("etag"),
        links=item.get("links"),
        assignment_info=item.get("assignmentInfo"),
    )
