# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""Google log presets (REQ-1996): Cloud Logging LogEntry exports, Android logcat in its threadtime
form, and Chrome's net-export (NetLog) files, each in the form its documentation gives."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.formats import RegexFormat
from provisa.logparse.presets._shared import JsonFormat, utc

GROUP = "google"

# --- Cloud Logging LogEntry exports ------------------------------------------------------------


class CloudLogging(JsonFormat):
    """Cloud Logging LogEntry records as a sink exports them: one JSON object a line, or a JSON
    array of them, each entry a row. Its payload is whichever of text, JSON or proto it carries."""

    def __init__(self) -> None:
        super().__init__(
            "gcp_cloud_logging",
            "Google Cloud Logging export",
            GROUP,
            [
                (Column("timestamp", "timestamp"), "timestamp"),
                (Column("receive_timestamp", "timestamp"), "receiveTimestamp"),
                (Column("severity", "string"), "severity"),
                (Column("log_name", "string"), "logName"),
                (Column("insert_id", "string"), "insertId"),
                (Column("resource_type", "string"), "resource.type"),
                (Column("resource_labels", "json"), "resource.labels"),
                (Column("labels", "json"), "labels"),
                (Column("trace", "string"), "trace"),
                (Column("span_id", "string"), "spanId"),
                (Column("http_request", "json"), "httpRequest"),
                (Column("operation", "json"), "operation"),
                (Column("source_location", "json"), "sourceLocation"),
                (Column("text_payload", "string"), "textPayload"),
                (Column("json_payload", "json"), "jsonPayload"),
                (Column("proto_payload", "json"), "protoPayload"),
            ],
            lambda row, doc: {
                **row,
                "timestamp": utc(row["timestamp"]),
                "receive_timestamp": utc(row["receive_timestamp"]),
            },
        )

    def parse_many(self, record: str, ctx: FileContext) -> list[dict[str, Any]]:
        try:
            doc = json.loads(record)
        except json.JSONDecodeError as exc:
            raise ParseError(f"not JSON: {exc.msg} at column {exc.colno}") from exc
        entries = doc if isinstance(doc, list) else [doc]
        if not all(isinstance(e, dict) for e in entries):
            raise ParseError(f"a {self.label} entry that is not an object")
        return [self.row(e) for e in entries]


# --- Android logcat (threadtime) ---------------------------------------------------------------

_LEVELS = {
    "V": "verbose",
    "D": "debug",
    "I": "info",
    "W": "warn",
    "E": "error",
    "F": "fatal",
    "S": "silent",
}


def _logcat(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    stamp = g["stamp"] or ""
    month = int(stamp[:2])
    # A threadtime line carries no year: the file's, unless its month comes after the file's last
    # write -- then the year before (as BSD syslog's).
    year = ctx.mtime.year - (1 if month > ctx.mtime.month else 0)
    try:
        when = datetime.strptime(f"{year}-{stamp}", "%Y-%m-%d %H:%M:%S.%f")
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc
    return {
        "timestamp": when.replace(tzinfo=ctx.mtime.tzinfo),
        "pid": g["pid"],
        "tid": g["tid"],
        "priority": _LEVELS[g["level"] or ""],
        "tag": (g["tag"] or "").strip(),
        "message": g["message"],
    }


LOGCAT = RegexFormat(
    "android_logcat",
    "Android logcat (threadtime)",
    GROUP,
    r"^(?P<stamp>\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<pid>\d+)\s+(?P<tid>\d+) "
    r"(?P<level>[VDIWEFS]) (?P<tag>[^:]*?)\s*: (?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("pid", "integer"),
        Column("tid", "integer"),
        Column("priority", "string"),
        Column("tag", "string"),
        Column("message", "string"),
    ],
    _logcat,
)

# --- Chrome net-export (NetLog JSON) ------------------------------------------------------------


def _names(constants: dict[str, Any], table: str, label: str) -> dict[int, str]:
    """A NetLog constants table (name -> number) turned round; a document without it is refused."""
    found = constants.get(table)
    if not isinstance(found, dict):
        raise ParseError(f"no constants.{table} in the {label} document")
    return {v: k for k, v in found.items()}


def _named(names: dict[int, str], value: Any, what: str) -> str:
    """The name the document's constants give ``value``; the constants are written by the same
    Chrome as the events, so a number they do not name is a malformed file."""
    if value not in names:
        raise ParseError(f"event {what} {value!r} is not named in the document's constants")
    return names[value]


class ChromeNetExport(Format):
    """A Chrome net-export file (chrome://net-export): one JSON document, its ``constants`` then
    its ``events``, each event a row. An event's time is milliseconds from the document's
    ``timeTickOffset``; its type, source type and phase are numbers the constants name."""

    name, label, group = "chrome_net_export", "Chrome net-export (NetLog)", GROUP
    record_start = re.compile(r'\{"constants"')

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("time", "timestamp"),
            Column("event_type", "string"),
            Column("phase", "string"),
            Column("source_id", "integer"),
            Column("source_type", "string"),
            Column("params", "json"),
            Column("extra", "json"),
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        raise ParseError(f"a {self.label} file is a batch of events, read by parse_many")

    def parse_many(self, record: str, ctx: FileContext) -> list[dict[str, Any]]:
        try:
            doc = json.loads(record)
        except json.JSONDecodeError as exc:
            raise ParseError(f"not a whole {self.label} document: {exc.msg}") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
            raise ParseError(f"no events list in the {self.label} document")
        constants = doc.get("constants") or {}
        offset = constants.get("timeTickOffset")
        if offset is None:
            raise ParseError(f"no constants.timeTickOffset in the {self.label} document")
        origin = datetime.fromtimestamp(int(offset) / 1000, tz=timezone.utc)
        types = _names(constants, "logEventTypes", self.label)
        sources = _names(constants, "logSourceType", self.label)
        phases = _names(constants, "logEventPhase", self.label)
        rows = []
        for event in doc["events"]:
            source = event.get("source") or {}
            rows.append(
                {
                    "time": origin + timedelta(milliseconds=int(event["time"])),
                    "event_type": _named(types, event.get("type"), "type"),
                    "phase": _named(phases, event.get("phase"), "phase"),
                    "source_id": source.get("id"),
                    "source_type": _named(sources, source.get("type"), "source type"),
                    "params": event.get("params"),
                }
            )
        return rows


PRESETS: list[Format] = [CloudLogging(), LOGCAT, ChromeNetExport()]
