# Copyright (c) 2026 Kenneth Stott
# Canary: 3f8a6b21-9c4d-4e70-b1a5-7d2e0c9f8b36
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The calendar and task tables of both mail sources, row by row (REQ-1994).

What Google and Microsoft answer for one item becomes rows of exactly the canonical columns,
of the canonical types, with every enumeration translated: so a union of the two sources'
tables needs no cast or rename. A series is a master row with its recurrence as RFC 5545 lines,
and a moved occurrence an exception row naming its series and original start.
"""

from __future__ import annotations

import datetime as dt

import pytest

from provisa.core import canonical_mail as cm
from provisa.core.ir_arrow import arrow_schema, rows_to_batch
from provisa.google_workspace import calendar_read
from provisa.google_workspace import calendar_rows as google
from provisa.microsoft365 import calendar as microsoft
from provisa.microsoft365.recurrence import RecurrenceRefused, from_rfc5545, to_rfc5545

ACCOUNT = "ada@example.test"

G_CALENDAR = {
    "id": "ada@example.test",
    "summary": "Ada",
    "timeZone": "Europe/London",
    "primary": True,
    "accessRole": "owner",
    "backgroundColor": "#9fe1e7",
    "etag": '"1"',
}
G_SERIES = {
    "id": "series1",
    "iCalUID": "series1@google.com",
    "summary": "Stand-up",
    "start": {"dateTime": "2026-10-12T09:00:00+01:00", "timeZone": "Europe/London"},
    "end": {"dateTime": "2026-10-12T09:15:00+01:00", "timeZone": "Europe/London"},
    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"],
    "status": "confirmed",
    "organizer": {"email": ACCOUNT, "self": True},
    "attendees": [
        {"email": ACCOUNT, "self": True, "organizer": True, "responseStatus": "accepted"},
        {"email": "bo@example.test", "optional": True, "responseStatus": "needsAction"},
    ],
    "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
    "updated": "2026-10-11T08:00:00.000Z",
    "created": "2026-10-01T08:00:00.000Z",
    "etag": '"2"',
}
G_MOVED = {
    "id": "series1_20261014T080000Z",
    "summary": "Stand-up (moved)",
    "recurringEventId": "series1",
    "originalStartTime": {"dateTime": "2026-10-14T09:00:00+01:00"},
    "start": {"dateTime": "2026-10-14T10:00:00+01:00"},
    "end": {"dateTime": "2026-10-14T10:15:00+01:00"},
    "status": "confirmed",
}
G_ALL_DAY = {
    "id": "holiday",
    "summary": "Holiday",
    "start": {"date": "2026-12-25"},
    "end": {"date": "2026-12-26"},
    "transparency": "transparent",
}
G_TASK = {
    "id": "t1",
    "title": "File the return",
    "notes": "before Friday",
    "status": "needsAction",
    "due": "2026-10-16T00:00:00.000Z",
    "updated": "2026-10-11T08:00:00.000Z",
    "etag": '"3"',
}

M_CALENDAR = {
    "id": "cal1",
    "name": "Calendar",
    "isDefaultCalendar": True,
    "canEdit": True,
    "owner": {"address": ACCOUNT},
    "hexColor": "",
    "changeKey": "ck1",
}
M_SERIES = {
    "id": "mseries",
    "subject": "Review",
    "body": {"contentType": "text", "content": "notes"},
    "start": {"dateTime": "2026-10-12T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-10-12T15:00:00.0000000", "timeZone": "UTC"},
    "originalStartTimeZone": "GMT Standard Time",
    "isAllDay": False,
    "isCancelled": False,
    "showAs": "busy",
    "sensitivity": "normal",
    "importance": "normal",
    "type": "seriesMaster",
    "recurrence": {
        "pattern": {
            "type": "relativeMonthly",
            "interval": 1,
            "daysOfWeek": ["tuesday"],
            "index": "second",
        },
        "range": {"type": "numbered", "startDate": "2026-10-12", "numberOfOccurrences": 6},
    },
    "isOrganizer": True,
    "organizer": {"emailAddress": {"address": ACCOUNT, "name": "Ada"}},
    "attendees": [
        {
            "type": "required",
            "status": {"response": "accepted", "time": "2026-10-11T08:00:00Z"},
            "emailAddress": {"address": "bo@example.test", "name": "Bo"},
        }
    ],
    "isReminderOn": True,
    "reminderMinutesBeforeStart": 15,
    "responseStatus": {"response": "organizer"},
    "lastModifiedDateTime": "2026-10-11T08:00:00.1234567Z",
}
M_EXCEPTION = {
    "id": "mexception",
    "subject": "Review (moved)",
    "type": "exception",
    "seriesMasterId": "mseries",
    "originalStart": "2026-11-10T14:00:00Z",
    "start": {"dateTime": "2026-11-11T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-11-11T15:00:00.0000000", "timeZone": "UTC"},
    "isAllDay": False,
    "isCancelled": False,
    "showAs": "busy",
    "sensitivity": "normal",
}
M_LIST = {"id": "l1", "displayName": "Tasks", "wellknownListName": "defaultList", "isShared": False}
M_TASK = {
    "id": "mt1",
    "title": "Call Bo",
    "body": {"content": "about the review", "contentType": "text"},
    "status": "inProgress",
    "importance": "high",
    "dueDateTime": {"dateTime": "2026-10-16T00:00:00.0000000", "timeZone": "UTC"},
    "reminderDateTime": {"dateTime": "2026-10-15T09:00:00.0000000", "timeZone": "UTC"},
    "isReminderOn": True,
    "lastModifiedDateTime": "2026-10-11T08:00:00Z",
}


def _google_rows() -> dict[str, list[dict]]:
    events, people = [], []
    for item in (G_SERIES, G_MOVED, G_ALL_DAY):
        event, attendees = google.event_rows(ACCOUNT, G_CALENDAR["id"], item)
        events.append(event)
        people.extend(attendees)
    return {
        "calendars": [google.calendar_row(ACCOUNT, G_CALENDAR)],
        "events": events,
        "event_attendees": people,
        "task_lists": [google.task_list_row(ACCOUNT, {"id": "l1", "title": "My Tasks"})],
        "tasks": [google.task_row(ACCOUNT, "l1", G_TASK)],
    }


def _microsoft_rows() -> dict[str, list[dict]]:
    events, people = [], []
    for item in (M_SERIES, M_EXCEPTION):
        event, attendees = microsoft.event_rows(ACCOUNT, "cal1", item)
        events.append(event)
        people.extend(attendees)
    return {
        "calendars": [microsoft.calendar_row(ACCOUNT, M_CALENDAR)],
        "events": events,
        "event_attendees": people,
        "task_lists": [microsoft.task_list_row(ACCOUNT, M_LIST)],
        "tasks": [microsoft.task_row(ACCOUNT, "l1", M_TASK)],
    }


PROVIDERS = {cm.GOOGLE: _google_rows, cm.MICROSOFT: _microsoft_rows}
TABLES = ("calendars", "events", "event_attendees", "task_lists", "tasks")


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize("table", TABLES)
def test_rows_have_exactly_the_canonical_columns_of_the_canonical_types(provider, table):
    rows = PROVIDERS[provider]()[table]
    columns = cm.ir_columns(table)
    assert rows and all(list(row) == [name for name, _ in columns] for row in rows)
    batch = rows_to_batch(rows, columns, arrow_schema(columns))
    assert batch.num_rows == len(rows)
    assert {(r["provider"], r["account"]) for r in rows} == {(provider, ACCOUNT)}
    for row in rows:
        for column in cm.TABLES[table].columns:
            if not column.populated_by(provider):
                assert row[column.name] is None, (table, column.name)


def test_a_google_series_and_its_moved_occurrence():
    series, moved, all_day = _google_rows()["events"]
    assert (series["kind"], series["recurrence"]) == (
        "series_master",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE",
    )
    assert series["start_at"] == dt.datetime(2026, 10, 12, 8, tzinfo=dt.UTC)
    assert series["reminders"]["overrides"] == [{"method": "popup", "minutes": 10}]
    assert (moved["kind"], moved["series_id"]) == ("exception", "series1")
    assert moved["original_start_at"] == dt.datetime(2026, 10, 14, 8, tzinfo=dt.UTC)
    assert (all_day["is_all_day"], all_day["start_date"], all_day["start_at"]) == (
        True,
        dt.date(2026, 12, 25),
        None,
    )
    assert all_day["show_as"] == "free"


def test_google_attendees_and_the_accounts_own_answer():
    series = _google_rows()["events"][0]
    me, bo = _google_rows()["event_attendees"]
    assert series["my_response"] == "accepted"
    assert (me["is_self"], me["is_organizer"], me["position"]) == (True, True, 1)
    assert (bo["address"], bo["kind"], bo["response"]) == (
        "bo@example.test",
        "optional",
        "needs_action",
    )


def test_a_google_task_keeps_the_day_it_is_due():
    (task,) = _google_rows()["tasks"]
    assert (task["status"], task["due_date"], task["reminder_at"]) == (
        "open",
        dt.date(2026, 10, 16),
        None,
    )


def test_only_a_cancelled_occurrence_of_a_live_series_is_a_google_row():
    """Google answers ``cancelled`` for an event deleted outright too; that is not a row."""
    assert calendar_read._live({"status": "cancelled", "recurringEventId": "s"})
    assert not calendar_read._live({"status": "cancelled"})
    assert calendar_read._live({"status": "confirmed"})


def test_a_microsoft_series_renders_its_pattern_as_one_rrule():
    series, exception = _microsoft_rows()["events"]
    assert series["recurrence"] == "RRULE:FREQ=MONTHLY;BYDAY=2TU;COUNT=6"
    assert (series["kind"], series["my_response"], series["is_organizer"]) == (
        "series_master",
        None,
        True,
    )
    assert series["start_at"] == dt.datetime(2026, 10, 12, 14, tzinfo=dt.UTC)
    assert series["updated_at"] == dt.datetime(2026, 10, 11, 8, 0, 0, 123456, tzinfo=dt.UTC)
    assert (series["is_reminder_on"], series["reminder_minutes_before_start"]) == (True, 15)
    assert (exception["kind"], exception["series_id"]) == ("exception", "mseries")
    assert exception["original_start_at"] == dt.datetime(2026, 11, 10, 14, tzinfo=dt.UTC)


def test_a_microsoft_task_keeps_its_due_time_and_reminder():
    (task,) = _microsoft_rows()["tasks"]
    assert (task["status"], task["vendor_status"], task["importance"]) == (
        "open",
        "inProgress",
        "high",
    )
    assert task["due_at"] == dt.datetime(2026, 10, 16, tzinfo=dt.UTC)
    assert task["reminder_at"] == dt.datetime(2026, 10, 15, 9, tzinfo=dt.UTC)


def test_a_time_graph_answers_in_another_zone_is_refused():
    with pytest.raises(microsoft.UnexpectedAnswer, match="Pacific"):
        microsoft.instant({"dateTime": "2026-10-12T09:00:00", "timeZone": "Pacific Standard Time"})


# -- recurrence -------------------------------------------------------------------------------

PATTERNS = [
    (
        {"pattern": {"type": "daily", "interval": 2}, "range": {"type": "noEnd"}},
        "RRULE:FREQ=DAILY;INTERVAL=2",
    ),
    (
        {
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": ["monday", "friday"],
                "firstDayOfWeek": "sunday",
            },
            "range": {"type": "endDate", "endDate": "2026-12-31"},
        },
        "RRULE:FREQ=WEEKLY;BYDAY=MO,FR;WKST=SU;UNTIL=20261231",
    ),
    (
        {
            "pattern": {"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 15},
            "range": {"type": "numbered", "numberOfOccurrences": 3},
        },
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=15;COUNT=3",
    ),
    (
        {
            "pattern": {
                "type": "relativeYearly",
                "interval": 1,
                "month": 11,
                "daysOfWeek": ["thursday"],
                "index": "fourth",
            },
            "range": {"type": "noEnd"},
        },
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=4TH",
    ),
    (
        {
            "pattern": {
                "type": "relativeMonthly",
                "interval": 1,
                "daysOfWeek": ["saturday", "sunday"],
                "index": "last",
            },
            "range": {"type": "noEnd"},
        },
        "RRULE:FREQ=MONTHLY;BYDAY=SA,SU;BYSETPOS=-1",
    ),
]


@pytest.mark.parametrize(("graph", "rule"), PATTERNS)
def test_a_graph_pattern_is_one_rrule_and_reads_back_as_the_same_pattern(graph, rule):
    assert to_rfc5545(graph) == rule
    back = from_rfc5545(rule, dt.date(2026, 10, 12), "UTC")
    for key, value in graph["pattern"].items():
        assert back["pattern"][key] == value, key
    assert back["range"]["type"] == graph["range"]["type"]


@pytest.mark.parametrize(
    "rule",
    [
        "RRULE:FREQ=HOURLY",
        "RRULE:FREQ=WEEKLY;BYWEEKNO=2",
        "RRULE:FREQ=DAILY\nEXDATE:20261014",
        "RRULE:FREQ=MONTHLY;BYDAY=TU",
    ],
)
def test_a_rule_graph_has_no_pattern_for_is_refused(rule):
    with pytest.raises(RecurrenceRefused):
        from_rfc5545(rule, dt.date(2026, 10, 12), "UTC")
