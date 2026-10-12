# Copyright (c) 2026 Kenneth Stott
# Canary: f364e17d-e2b4-41bd-b841-56427f31dad5
#
# This source code is licensed under the Business Source License 1.1
"""Database and runtime log presets (REQ-1996): PostgreSQL's stderr, csvlog and jsonlog, MySQL's
error and slow-query logs, MongoDB's structured log, Redis's log, the log4j 2 and logback default
patterns and Python logging's default format, each in the form its documentation gives. A record
that spans lines (a stack trace, a slow query, a multi-line statement) is read whole."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.formats import RegexFormat
from provisa.logparse.presets._shared import JsonFormat, utc

GROUP = "databases"

_UTC_NAMES = {"UTC", "GMT", "Z"}


def _pg_time(stamp: str, ctx: FileContext) -> datetime:
    """A PostgreSQL log time, ``2023-05-11 08:15:23.456 UTC``: its zone is log_timezone, written
    by abbreviation; UTC/GMT are read as such, any other as the server's local zone -- the zone of
    the file's last write."""
    when, _, zone = stamp.rpartition(" ")
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in when else "%Y-%m-%d %H:%M:%S"
    try:
        value = datetime.strptime(when, fmt)
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc
    if zone in _UTC_NAMES:
        return value.replace(tzinfo=timezone.utc)
    offset = re.fullmatch(r"([+-])(\d{2}):?(\d{2})?", zone)
    if offset:
        sign = -1 if offset.group(1) == "-" else 1
        delta = timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3) or 0))
        return value.replace(tzinfo=timezone(sign * delta))
    return value.replace(tzinfo=ctx.mtime.tzinfo)


# --- PostgreSQL stderr (log_line_prefix = '%m [%p] ', the default) -----------------------------

_PG_STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? \S+"


def _pg_stderr(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": _pg_time(g["stamp"] or "", ctx),
        "pid": g["pid"],
        "severity": g["severity"],
        "message": g["message"],
    }


PG_STDERR = RegexFormat(
    "postgresql_stderr",
    "PostgreSQL log (stderr)",
    GROUP,
    rf"^(?P<stamp>{_PG_STAMP}) \[(?P<pid>\d+)\] (?P<severity>[A-Z0-9]+):\s+(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("pid", "integer"),
        Column("severity", "string"),
        Column("message", "string"),
    ],
    _pg_stderr,
    # A message's further lines (a multi-line statement) are indented with a tab.
    record_start=_PG_STAMP + r" \[\d+\] ",
    flags=re.DOTALL,
)

# --- PostgreSQL csvlog -------------------------------------------------------------------------

_PG_CSV_FIELDS = [
    "log_time",
    "user_name",
    "database_name",
    "process_id",
    "connection_from",
    "session_id",
    "session_line_num",
    "command_tag",
    "session_start_time",
    "virtual_transaction_id",
    "transaction_id",
    "error_severity",
    "sql_state_code",
    "message",
    "detail",
    "hint",
    "internal_query",
    "internal_query_pos",
    "context",
    "query",
    "query_pos",
    "location",
    "application_name",
    # PostgreSQL 13
    "backend_type",
    # PostgreSQL 14
    "leader_pid",
    "query_id",
]
_PG_CSV_INTEGERS = {
    "process_id",
    "session_line_num",
    "transaction_id",
    "internal_query_pos",
    "query_pos",
    "leader_pid",
    "query_id",
}


class PgCsvLog(Format):
    """PostgreSQL's csvlog: one CSV record an event, a quoted field that holds a newline written
    over several lines; PostgreSQL 13 and 14 add columns at the end, an older log has fewer."""

    name, label, group = "postgresql_csvlog", "PostgreSQL csvlog", GROUP
    record_start = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column(
                f,
                "timestamp"
                if f in ("log_time", "session_start_time")
                else "integer"
                if f in _PG_CSV_INTEGERS
                else "string",
            )
            for f in _PG_CSV_FIELDS
        ] + [Column("extra", "json")]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        values = next(csv.reader([record]))
        if len(values) < 23:
            raise ParseError(f"{len(values)} fields, fewer than the 23 of the {self.label}")
        padded = values + [""] * (len(_PG_CSV_FIELDS) - len(values))
        row: dict[str, Any] = {f: (v or None) for f, v in zip(_PG_CSV_FIELDS, padded)}
        for f in ("log_time", "session_start_time"):
            if row[f] is not None:
                row[f] = _pg_time(row[f], ctx)
        return row


# --- PostgreSQL jsonlog (15 and later) ---------------------------------------------------------


class PgJsonLog(JsonFormat):
    """PostgreSQL's jsonlog: one JSON object an event; its times are written as stderr's are,
    with log_timezone's abbreviation."""

    def __init__(self) -> None:
        super().__init__(
            "postgresql_jsonlog",
            "PostgreSQL jsonlog",
            GROUP,
            [
                (Column("timestamp", "timestamp"), "timestamp"),
                (Column("user", "string"), "user"),
                (Column("dbname", "string"), "dbname"),
                (Column("pid", "integer"), "pid"),
                (Column("remote_host", "string"), "remote_host"),
                (Column("session_id", "string"), "session_id"),
                (Column("line_num", "integer"), "line_num"),
                (Column("ps", "string"), "ps"),
                (Column("session_start", "timestamp"), "session_start"),
                (Column("vxid", "string"), "vxid"),
                (Column("txid", "integer"), "txid"),
                (Column("error_severity", "string"), "error_severity"),
                (Column("state_code", "string"), "state_code"),
                (Column("message", "string"), "message"),
                (Column("detail", "string"), "detail"),
                (Column("hint", "string"), "hint"),
                (Column("statement", "string"), "statement"),
                (Column("context", "string"), "context"),
                (Column("application_name", "string"), "application_name"),
                (Column("backend_type", "string"), "backend_type"),
                (Column("query_id", "integer"), "query_id"),
            ],
        )

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        row = self.row(self.load(record))
        for f in ("timestamp", "session_start"):
            if row[f] is not None:
                row[f] = _pg_time(row[f], ctx)
        return row


# --- MySQL error log (8.0) ---------------------------------------------------------------------


def _mysql_error(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": utc(g["time"]),
        "thread": g["thread"],
        "priority": g["priority"],
        "error_code": g["code"],
        "subsystem": g["subsystem"],
        "message": g["message"],
    }


MYSQL_ERROR = RegexFormat(
    "mysql_error",
    "MySQL error log",
    GROUP,
    r"^(?P<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})) "
    r"(?P<thread>\d+) \[(?P<priority>[A-Za-z]+)\] \[(?P<code>MY-\d+)\] \[(?P<subsystem>[^\]]+)\] "
    r"(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("thread", "integer"),
        Column("priority", "string"),
        Column("error_code", "string"),
        Column("subsystem", "string"),
        Column("message", "string"),
    ],
    _mysql_error,
    record_start=r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
    flags=re.DOTALL,
)

# --- MySQL slow-query log ----------------------------------------------------------------------

_SLOW = re.compile(
    r"^# Time: (?P<time>\S+)\n"
    r"# User@Host: (?P<user>\S*)\[[^\]]*\] @ (?P<host>\S*) \[(?P<ip>[^\]]*)\]\s+Id:\s+(?P<id>\d+)\n"
    r"# Query_time: (?P<query_time>[\d.]+)\s+Lock_time: (?P<lock_time>[\d.]+)\s+"
    r"Rows_sent: (?P<rows_sent>\d+)\s+Rows_examined: (?P<rows_examined>\d+)[^\n]*\n"
    r"(?:use (?P<db>[^;]+);\n)?(?:SET timestamp=(?P<stamp>\d+);\n)?(?P<query>.*)$",
    re.DOTALL,
)


class MySqlSlowLog(Format):
    """MySQL's slow-query log: an entry starts with ``# Time:``, then the user and host, the
    timings, an optional ``use``, the ``SET timestamp`` and the statement, over several lines."""

    name, label, group = "mysql_slow", "MySQL slow-query log", GROUP
    record_start = re.compile(r"# Time: ")

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("timestamp", "timestamp"),
            Column("user", "string"),
            Column("host", "string"),
            Column("ip", "string"),
            Column("connection_id", "integer"),
            Column("query_time_s", "float"),
            Column("lock_time_s", "float"),
            Column("rows_sent", "integer"),
            Column("rows_examined", "integer"),
            Column("database", "string"),
            Column("query", "string"),
            Column("extra", "json"),
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        m = _SLOW.match(record)
        if m is None:
            raise ParseError(f"not an entry of the {self.label}")
        g = m.groupdict()
        return {
            "timestamp": utc(g["time"]),
            "user": g["user"] or None,
            "host": g["host"] or None,
            "ip": g["ip"] or None,
            "connection_id": g["id"],
            "query_time_s": g["query_time"],
            "lock_time_s": g["lock_time"],
            "rows_sent": g["rows_sent"],
            "rows_examined": g["rows_examined"],
            "database": g["db"],
            "query": (g["query"] or "").strip(),
        }


# --- MongoDB structured log (4.4 and later) ----------------------------------------------------

MONGODB = JsonFormat(
    "mongodb",
    "MongoDB log",
    GROUP,
    [
        (Column("timestamp", "timestamp"), "t.$date"),
        (Column("severity", "string"), "s"),
        (Column("component", "string"), "c"),
        (Column("id", "integer"), "id"),
        (Column("context", "string"), "ctx"),
        (Column("message", "string"), "msg"),
        (Column("attributes", "json"), "attr"),
        (Column("tags", "json"), "tags"),
        (Column("truncated", "json"), "truncated"),
    ],
    lambda row, doc: {**row, "timestamp": utc(row["timestamp"])},
)

# --- Redis -------------------------------------------------------------------------------------

_REDIS_ROLES = {"X": "sentinel", "C": "child", "S": "replica", "M": "master"}
_REDIS_LEVELS = {".": "debug", "-": "verbose", "*": "notice", "#": "warning"}


def _redis(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    try:
        when = datetime.strptime(g["time"] or "", "%d %b %Y %H:%M:%S.%f")
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {g['time']!r}") from exc
    return {
        "timestamp": when.replace(tzinfo=ctx.mtime.tzinfo),
        "pid": g["pid"],
        "role": _REDIS_ROLES[g["role"] or ""],
        "level": _REDIS_LEVELS[g["level"] or ""],
        "message": g["message"],
    }


REDIS = RegexFormat(
    "redis",
    "Redis log",
    GROUP,
    r"^(?P<pid>\d+):(?P<role>[XCSM]) (?P<time>\d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<level>[.\-*#]) (?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("pid", "integer"),
        Column("role", "string"),
        Column("level", "string"),
        Column("message", "string"),
    ],
    _redis,
)

# --- log4j 2 / logback default patterns --------------------------------------------------------

_JAVA_START = r"\d{2}:\d{2}:\d{2}\.\d{3} \["


def _java(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    # The default pattern writes the time of day only: the day is the file's last write's.
    try:
        clock = datetime.strptime(g["time"] or "", "%H:%M:%S.%f").time()
    except ValueError as exc:
        raise ParseError(f"not a time of day: {g['time']!r}") from exc
    return {
        "timestamp": datetime.combine(ctx.mtime.date(), clock, tzinfo=ctx.mtime.tzinfo),
        "thread": g["thread"],
        "level": g["level"],
        "logger": g["logger"],
        "message": g["message"],
    }


_JAVA_COLUMNS = [
    Column("timestamp", "timestamp"),
    Column("thread", "string"),
    Column("level", "string"),
    Column("logger", "string"),
    Column("message", "string"),
]
_JAVA_PATTERN = (
    r"^(?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) \[(?P<thread>[^\]]*)\] "
    r"(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+(?P<logger>\S+) - (?P<message>.*)$"
)

LOG4J = RegexFormat(
    "log4j2_default",
    "log4j 2 default pattern",
    GROUP,
    _JAVA_PATTERN,
    _JAVA_COLUMNS,
    _java,
    record_start=_JAVA_START,
    flags=re.DOTALL,
)
LOGBACK = RegexFormat(
    "logback_default",
    "logback default pattern",
    GROUP,
    _JAVA_PATTERN,
    _JAVA_COLUMNS,
    _java,
    record_start=_JAVA_START,
    flags=re.DOTALL,
)

# --- Python logging default format -------------------------------------------------------------

PYTHON_LOGGING = RegexFormat(
    "python_logging",
    "Python logging default format",
    GROUP,
    r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):(?P<logger>[^:]*):(?P<message>.*)$",
    [
        Column("level", "string"),
        Column("logger", "string"),
        Column("message", "string"),
    ],
    # A traceback's lines follow the message that logged it.
    record_start=r"(?:DEBUG|INFO|WARNING|ERROR|CRITICAL):",
    flags=re.DOTALL,
)

PRESETS: list[Format] = [
    PG_STDERR,
    PgCsvLog(),
    PgJsonLog(),
    MYSQL_ERROR,
    MySqlSlowLog(),
    MONGODB,
    REDIS,
    LOG4J,
    LOGBACK,
    PYTHON_LOGGING,
]
