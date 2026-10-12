# Copyright (c) 2026 Kenneth Stott
# Canary: 5c9e0a47-3d1b-4f86-a2c8-7b4d6e9f1035
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Graph's structured recurrence as RFC 5545 lines, and back (REQ-1994).

``events.recurrence`` has one encoding for both providers: RFC 5545 lines, as Google writes them.
Graph states a recurrence as a pattern (how it repeats) and a range (when it ends), which
:func:`to_rfc5545` renders as one ``RRULE`` line and :func:`from_rfc5545` reads back. Every
pattern Graph has is rendered; a rule Graph has no pattern for (an hourly rule, ``BYWEEKNO``,
more than one ``RRULE``) is refused by name when written.
"""

# Requirements: REQ-1994
from __future__ import annotations

import datetime as dt
from typing import Any

_DAYS = {
    "sunday": "SU",
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
}
_DAY_NAMES = {v: k for k, v in _DAYS.items()}
_INDEX = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}
_INDEX_NAMES = {v: k for k, v in _INDEX.items()}
_FREQ = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "absoluteMonthly": "MONTHLY",
    "relativeMonthly": "MONTHLY",
    "absoluteYearly": "YEARLY",
    "relativeYearly": "YEARLY",
}


class RecurrenceRefused(ValueError):
    """A rule Graph has no pattern for."""


def to_rfc5545(recurrence: dict | None) -> str | None:
    """Graph's ``patternedRecurrence`` as one ``RRULE`` line; None for no recurrence."""
    if not recurrence:
        return None
    pattern, span = recurrence["pattern"], recurrence.get("range") or {}
    kind = pattern["type"]
    parts = [f"FREQ={_FREQ[kind]}"]
    if (pattern.get("interval") or 1) != 1:
        parts.append(f"INTERVAL={pattern['interval']}")
    days = [_DAYS[d] for d in pattern.get("daysOfWeek") or []]
    if kind == "weekly":
        parts.append(f"BYDAY={','.join(days)}")
        first = pattern.get("firstDayOfWeek")
        if first and first != "monday":
            parts.append(f"WKST={_DAYS[first]}")
    elif kind in ("absoluteMonthly", "absoluteYearly"):
        if kind == "absoluteYearly":
            parts.append(f"BYMONTH={pattern['month']}")
        parts.append(f"BYMONTHDAY={pattern['dayOfMonth']}")
    elif kind in ("relativeMonthly", "relativeYearly"):
        if kind == "relativeYearly":
            parts.append(f"BYMONTH={pattern['month']}")
        index = _INDEX[pattern.get("index") or "first"]
        if len(days) == 1:
            parts.append(f"BYDAY={index}{days[0]}")
        else:
            parts.append(f"BYDAY={','.join(days)}")
            parts.append(f"BYSETPOS={index}")
    ending = span.get("type")
    if ending == "endDate":
        parts.append(f"UNTIL={span['endDate'].replace('-', '')}")
    elif ending == "numbered":
        parts.append(f"COUNT={span['numberOfOccurrences']}")
    return "RRULE:" + ";".join(parts)


def _rule(text: str) -> dict[str, str]:
    lines = [line for line in text.splitlines() if line.strip()]
    rules = [line for line in lines if line.upper().startswith("RRULE:")]
    others = [line for line in lines if not line.upper().startswith("RRULE:")]
    if len(rules) != 1 or others:
        raise RecurrenceRefused(
            "a Microsoft 365 event repeats by one RRULE line and nothing else (no RDATE, EXDATE "
            "or second rule); remove an occurrence by deleting it"
        )
    out: dict[str, str] = {}
    for part in rules[0].split(":", 1)[1].split(";"):
        key, _, value = part.partition("=")
        out[key.upper()] = value.upper()
    return out


def _weekdays(value: str) -> list[str]:
    days = []
    for code in value.split(","):
        if code not in _DAY_NAMES:
            raise RecurrenceRefused(f"BYDAY={value}: a day is one of {', '.join(_DAY_NAMES)}")
        days.append(_DAY_NAMES[code])
    return days


def from_rfc5545(text: str, start: dt.date, time_zone: str) -> dict[str, Any]:
    """Graph's ``patternedRecurrence`` for one ``RRULE`` line, the series starting on ``start``."""
    rule = _rule(text)
    known = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "COUNT", "UNTIL"}
    known.add("WKST")
    unread = sorted(set(rule) - known)
    if unread:
        raise RecurrenceRefused(f"{', '.join(unread)}: Graph has no pattern for it")
    freq = rule.get("FREQ")
    pattern: dict[str, Any] = {"interval": int(rule.get("INTERVAL", "1"))}
    byday = rule.get("BYDAY")
    if freq == "DAILY":
        pattern["type"] = "daily"
    elif freq == "WEEKLY":
        pattern["type"] = "weekly"
        pattern["daysOfWeek"] = _weekdays(byday) if byday else [_weekday(start)]
        pattern["firstDayOfWeek"] = _DAY_NAMES[rule.get("WKST", "MO")]
    elif freq in ("MONTHLY", "YEARLY"):
        yearly = freq == "YEARLY"
        if yearly:
            pattern["month"] = int(rule.get("BYMONTH", str(start.month)))
        if byday:
            index, days = _relative(byday, rule.get("BYSETPOS"))
            pattern.update(
                type="relativeYearly" if yearly else "relativeMonthly",
                daysOfWeek=days,
                index=_INDEX_NAMES[index],
            )
        else:
            pattern.update(
                type="absoluteYearly" if yearly else "absoluteMonthly",
                dayOfMonth=int(rule.get("BYMONTHDAY", str(start.day))),
            )
    else:
        raise RecurrenceRefused(f"FREQ={freq}: Graph repeats daily, weekly, monthly or yearly")
    span: dict[str, Any] = {"startDate": start.isoformat(), "recurrenceTimeZone": time_zone}
    if "COUNT" in rule:
        span.update(type="numbered", numberOfOccurrences=int(rule["COUNT"]))
    elif "UNTIL" in rule:
        until = rule["UNTIL"][:8]
        span.update(type="endDate", endDate=f"{until[:4]}-{until[4:6]}-{until[6:8]}")
    else:
        span["type"] = "noEnd"
    return {"pattern": pattern, "range": span}


def _weekday(day: dt.date) -> str:
    return list(_DAY_NAMES.values())[(day.weekday() + 1) % 7]


def _relative(byday: str, setpos: str | None) -> tuple[int, list[str]]:
    """``BYDAY=2TU`` (one day with its index) or ``BYDAY=TU,TH;BYSETPOS=2``."""
    codes = byday.split(",")
    if len(codes) == 1 and codes[0][:-2]:
        index, code = int(codes[0][:-2]), codes[0][-2:]
        if index not in _INDEX_NAMES:
            raise RecurrenceRefused(f"BYDAY={byday}: Graph counts first to fourth, or last")
        return index, _weekdays(code)
    if setpos is None:
        raise RecurrenceRefused(
            f"BYDAY={byday} without an index: a monthly or yearly rule on weekdays says which "
            "(BYDAY=2TU, or BYSETPOS)"
        )
    index = int(setpos)
    if index not in _INDEX_NAMES:
        raise RecurrenceRefused(f"BYSETPOS={setpos}: Graph counts first to fourth, or last")
    return index, _weekdays(byday)
