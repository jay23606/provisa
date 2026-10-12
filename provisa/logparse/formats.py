# Copyright (c) 2026 Kenneth Stott
# Canary: 7c2e63fe-06c9-4b78-8277-b08370da99cc
#
# This source code is licensed under the Business Source License 1.1
"""The built-in log formats (REQ-1996): BSD syslog (RFC 3164), RFC 5424 syslog, the macOS
install-log form, Common and Combined Log Format, JSON lines, logfmt, W3C extended, CEF, GELF,
and a regular expression whose named groups are the columns."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.coltypes import infer_type

CORE = "Common formats"

_MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _int(value: str | None) -> int | None:
    return None if value in (None, "", "-") else int(value)  # type: ignore[arg-type]


def _nil(value: str | None) -> str | None:
    return None if value in (None, "-") else value


class RegexFormat(Format):
    """A format read by one regular expression whose named groups are its fields; ``convert``
    turns the groups into the row (typing, derived columns). A record that does not match is
    refused by the format's label."""

    def __init__(
        self,
        name: str,
        label: str,
        group: str,
        pattern: str,
        columns: list[Column],
        convert: Callable[[dict[str, str | None], FileContext], dict[str, Any]] | None = None,
        record_start: str | None = None,
        flags: int = 0,
    ) -> None:
        self.name, self.label, self.group = name, label, group
        self.pattern = re.compile(pattern, flags)
        self._columns = columns
        self._convert = convert
        self.record_start = re.compile(record_start) if record_start else None

    def columns(self, preview: list[str]) -> list[Column]:
        return list(self._columns)

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        m = self.pattern.match(record)
        if m is None:
            raise ParseError(f"not in the {self.label} form")
        groups = m.groupdict()
        return self._convert(groups, ctx) if self._convert else dict(groups)


# --- syslog ----------------------------------------------------------------------------------


def _pri(groups: dict[str, str | None]) -> dict[str, int | None]:
    pri = _int(groups.get("pri"))
    return {
        "facility": None if pri is None else pri // 8,
        "severity": None if pri is None else pri % 8,
    }


def _bsd_time(stamp: str, ctx: FileContext) -> datetime:
    month = _MONTHS.get(stamp[:3])
    if month is None:
        raise ParseError(f"no month in {stamp!r}")
    # The line carries no year: the year it was written in is the file's, unless the line's month
    # comes after the file's last write -- then it was written the year before.
    year = ctx.mtime.year - (1 if month > ctx.mtime.month else 0)
    return datetime.strptime(f"{year} {stamp}", "%Y %b %d %H:%M:%S").replace(
        tzinfo=ctx.mtime.tzinfo
    )


def _rfc3164(groups: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": _bsd_time(groups["timestamp"] or "", ctx),
        **_pri(groups),
        "host": groups["host"],
        "process": groups["process"],
        "pid": _int(groups["pid"]),
        "message": groups["message"],
    }


RFC3164 = RegexFormat(
    "rfc3164",
    "BSD syslog (RFC 3164)",
    CORE,
    r"^(?:<(?P<pri>\d{1,3})>)?(?P<timestamp>[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2}) "
    r"(?P<host>\S+) (?P<process>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?: ?(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("facility", "integer"),
        Column("severity", "integer"),
        Column("host", "string"),
        Column("process", "string"),
        Column("pid", "integer"),
        Column("message", "string"),
    ],
    _rfc3164,
    # macOS writes a message's further lines indented under it (an ASL module's rules): a
    # record is a line that starts with a timestamp and the lines after it that do not.
    record_start=r"(?:<\d{1,3}>)?[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} ",
    flags=re.DOTALL,
)

_SD_ELEMENT = re.compile(r'\[(?P<id>[^\s\]=]+)(?P<params>(?:\s+[^\s=\]]+="(?:\\.|[^"\\])*")*)\]')
_SD_PARAM = re.compile(r'([^\s=\]]+)="((?:\\.|[^"\\])*)"')


def _structured_data(text: str) -> dict[str, dict[str, str]] | None:
    if text == "-":
        return None
    elements: dict[str, dict[str, str]] = {}
    pos = 0
    while pos < len(text):
        m = _SD_ELEMENT.match(text, pos)
        if m is None:
            raise ParseError(
                f"structured data not in the RFC 5424 form at {text[pos : pos + 20]!r}"
            )
        elements[m["id"]] = {
            k: re.sub(r"\\([\"\\\]])", r"\1", v) for k, v in _SD_PARAM.findall(m["params"])
        }
        pos = m.end()
    return elements


def _rfc5424(groups: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    stamp = _nil(groups["timestamp"])
    message = groups["message"]
    if message and message.startswith("\ufeff"):
        message = message[1:]  # the BOM RFC 5424 puts before a UTF-8 message
    return {
        "timestamp": None
        if stamp is None
        else datetime.fromisoformat(stamp.replace("Z", "+00:00")),
        **_pri(groups),
        "version": _int(groups["version"]),
        "host": _nil(groups["host"]),
        "app": _nil(groups["app"]),
        "procid": _nil(groups["procid"]),
        "msgid": _nil(groups["msgid"]),
        "structured_data": _structured_data(groups["sd"] or "-"),
        "message": message,
    }


RFC5424 = RegexFormat(
    "rfc5424",
    "Syslog (RFC 5424)",
    CORE,
    r"^<(?P<pri>\d{1,3})>(?P<version>\d{1,2}) (?P<timestamp>\S+) (?P<host>\S+) (?P<app>\S+) "
    r"(?P<procid>\S+) (?P<msgid>\S+) (?P<sd>-|(?:\[(?:\\.|[^\]\\])*\])+)(?: (?P<message>.*))?$",
    [
        Column("timestamp", "timestamp"),
        Column("facility", "integer"),
        Column("severity", "integer"),
        Column("version", "integer"),
        Column("host", "string"),
        Column("app", "string"),
        Column("procid", "string"),
        Column("msgid", "string"),
        Column("structured_data", "json"),
        Column("message", "string"),
    ],
    _rfc5424,
    flags=re.DOTALL,
)


def _macos_install(groups: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    # "2026-08-30 14:18:15-04": an hours-only offset, which fromisoformat reads as it stands.
    # The entries written while the system starts are in the BSD form, with no year or offset.
    iso = groups["timestamp"]
    return {
        "timestamp": datetime.fromisoformat(iso) if iso else _bsd_time(groups["bsd"] or "", ctx),
        "host": groups["host"],
        "process": groups["process"],
        "pid": _int(groups["pid"]),
        "message": groups["message"],
    }


MACOS_INSTALL = RegexFormat(
    "macos_install",
    "macOS install log",
    CORE,
    r"^(?:(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{2}(?::?\d{2})?)"
    r"|(?P<bsd>[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2})) (?P<host>\S+) "
    # A process's name may hold spaces ("Software Update[55042]"): it runs to its [pid] or ':'.
    r"(?P<process>[^:\[\n]+?)(?:\[(?P<pid>\d+)\])?: ?(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("host", "string"),
        Column("process", "string"),
        Column("pid", "integer"),
        Column("message", "string"),
    ],
    _macos_install,
    # An installer's package list and a script's output go on indented lines under the entry.
    record_start=r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{2}|[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} ",
    flags=re.DOTALL,
)

# --- web access logs -----------------------------------------------------------------------

_CLF_STAMP = "%d/%b/%Y:%H:%M:%S %z"
_REQUEST = re.compile(r"^(?P<method>[A-Z]+) (?P<path>\S+)(?: (?P<protocol>\S+))?$")
_CLF_COLUMNS = [
    Column("timestamp", "timestamp"),
    Column("client", "string"),
    Column("ident", "string"),
    Column("user", "string"),
    Column("request", "string"),
    Column("method", "string"),
    Column("path", "string"),
    Column("protocol", "string"),
    Column("status", "integer"),
    Column("bytes", "integer"),
]


def _clf(groups: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    request = groups["request"] or ""
    parts = _REQUEST.match(request)
    row: dict[str, Any] = {
        "timestamp": datetime.strptime(groups["timestamp"] or "", _CLF_STAMP),
        "client": groups["client"],
        "ident": _nil(groups["ident"]),
        "user": _nil(groups["user"]),
        "request": request,
        "method": parts["method"] if parts else None,
        "path": parts["path"] if parts else None,
        "protocol": parts["protocol"] if parts else None,
        "status": _int(groups["status"]),
        "bytes": _int(groups["bytes"]),
    }
    if "referer" in groups:
        row["referer"] = _nil(groups["referer"])
        row["user_agent"] = _nil(groups["user_agent"])
    return row


_CLF_PATTERN = (
    r"^(?P<client>\S+) (?P<ident>\S+) (?P<user>\S+) \[(?P<timestamp>[^\]]+)\] "
    r'"(?P<request>(?:\\.|[^"\\])*)" (?P<status>\d{3}|-) (?P<bytes>\d+|-)'
)
CLF = RegexFormat("clf", "Common Log Format", CORE, _CLF_PATTERN + r"$", _CLF_COLUMNS, _clf)
COMBINED = RegexFormat(
    "combined",
    "Combined Log Format",
    CORE,
    _CLF_PATTERN + r' "(?P<referer>(?:\\.|[^"\\])*)" "(?P<user_agent>(?:\\.|[^"\\])*)"$',
    [*_CLF_COLUMNS, Column("referer", "string"), Column("user_agent", "string")],
    _clf,
)

# --- self-describing records: JSON lines, logfmt ---------------------------------------------


class _NamedFields(Format):
    """A format whose records name their own fields: its columns are the fields a preview saw,
    typed from their values; a field a later record carries that the columns lack is kept in
    ``extra``."""

    def fields(self, record: str) -> dict[str, Any]:
        raise NotImplementedError

    def columns(self, preview: list[str]) -> list[Column]:
        seen: dict[str, list[Any]] = {}
        for record in preview:
            try:
                for k, v in self.fields(record).items():
                    seen.setdefault(k, []).append(v)
            except ParseError:
                continue
        return [Column(k, infer_type(v)) for k, v in seen.items()] + [Column("extra", "json")]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        return self.fields(record)


class JsonLines(_NamedFields):
    name, label, group = "jsonl", "JSON lines", CORE

    def fields(self, record: str) -> dict[str, Any]:
        try:
            value = json.loads(record)
        except json.JSONDecodeError as exc:
            raise ParseError(f"not JSON: {exc.msg} at column {exc.colno}") from exc
        if not isinstance(value, dict):
            raise ParseError(f"a JSON {type(value).__name__}, not an object")
        return value


_LOGFMT = re.compile(r'\s*([^\s=]+)(?:=("(?:\\.|[^"\\])*"|[^\s"]*))?')


class Logfmt(_NamedFields):
    name, label, group = "logfmt", "logfmt", CORE

    def fields(self, record: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        pos = 0
        text = record.rstrip()
        while pos < len(text):
            m = _LOGFMT.match(text, pos)
            if m is None or m.end() == pos:
                raise ParseError(f"not key=value at {text[pos : pos + 20]!r}")
            key, raw = m.group(1), m.group(2)
            if raw is None:
                out[key] = True  # a bare key is a flag
            elif raw.startswith('"'):
                out[key] = json.loads(raw)
            else:
                out[key] = raw
            pos = m.end()
        if not out:
            raise ParseError("no key=value pairs")
        return out


# --- header-declared columns: W3C extended -----------------------------------------------------


def _column_name(field: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", field).strip("_").lower()


class W3C(Format):
    """W3C extended log format (IIS, and the presets that share it): the ``#Fields:`` directive
    names each file's columns; ``-`` is no value; ``date`` and ``time`` join into ``timestamp``.
    A field a file's header names that the table lacks is kept in ``extra``."""

    name, label, group = "w3c", "W3C extended (IIS)", CORE
    header_prefix = "#"
    separator: str | None = None  # None: runs of whitespace

    def _header_fields(self, preview: list[str]) -> list[str]:
        for line in preview:
            if line.startswith("#Fields:"):
                return line[len("#Fields:") :].split()
        return []

    def columns(self, preview: list[str]) -> list[Column]:
        fields = self._header_fields(preview)
        values: dict[str, list[str]] = {f: [] for f in fields}
        for line in preview:
            if not line or line.startswith("#"):
                continue
            for f, v in zip(fields, self._split(line)):
                values[f].append("" if v == "-" else v)
        cols: list[Column] = []
        if "date" in fields and "time" in fields:
            cols.append(Column("timestamp", "timestamp"))
        cols += [
            Column(_column_name(f), infer_type(values[f]))
            for f in fields
            if f not in ("date", "time")
        ]
        return cols + [Column("extra", "json")]

    def _split(self, line: str) -> list[str]:
        return line.split(self.separator) if self.separator else line.split()

    def on_header(self, line: str, ctx: FileContext) -> None:
        name, _, value = line[1:].partition(":")
        if name == "Fields":
            ctx.fields = value.split()
        else:
            ctx.directives[name] = value.strip()

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        if not ctx.fields:
            raise ParseError("no #Fields header before this line")
        values = self._split(record)
        if len(values) != len(ctx.fields):
            raise ParseError(f"{len(values)} values for the header's {len(ctx.fields)} fields")
        named = {f: (None if v == "-" else v) for f, v in zip(ctx.fields, values)}
        row: dict[str, Any] = {}
        if "date" in named and "time" in named and named["date"] and named["time"]:
            row["timestamp"] = datetime.fromisoformat(
                f"{named.pop('date')}T{named.pop('time')}"
            ).replace(tzinfo=timezone.utc)
        for f, v in named.items():
            row[_column_name(f)] = v
        return row


# --- security event formats: CEF, GELF ---------------------------------------------------------

_CEF_HEADER = re.compile(
    r"CEF:(\d+)\|((?:\\.|[^|\\])*)\|((?:\\.|[^|\\])*)\|((?:\\.|[^|\\])*)\|"
    r"((?:\\.|[^|\\])*)\|((?:\\.|[^|\\])*)\|((?:\\.|[^|\\])*)\|(.*)$",
    re.DOTALL,
)
_CEF_KEY = re.compile(r"(?:^|\s)([A-Za-z0-9_.\[\]]+)=")


def _cef_unescape(text: str) -> str:
    return re.sub(
        r"\\([|\\=nr])", lambda m: {"n": "\n", "r": "\r"}.get(m.group(1), m.group(1)), text
    )


class CEF(Format):
    name, label, group = "cef", "ArcSight CEF", CORE

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("cef_version", "integer"),
            Column("device_vendor", "string"),
            Column("device_product", "string"),
            Column("device_version", "string"),
            Column("signature_id", "string"),
            Column("name", "string"),
            Column("severity", "string"),
            Column("extension", "json"),
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        at = record.find("CEF:")  # a syslog header may come before it
        m = _CEF_HEADER.match(record, at) if at >= 0 else None
        if m is None:
            raise ParseError("not in the CEF form")
        ext_text = m.group(8)
        keys = list(_CEF_KEY.finditer(ext_text))
        extension = {}
        for i, k in enumerate(keys):
            end = keys[i + 1].start() if i + 1 < len(keys) else len(ext_text)
            extension[k.group(1)] = _cef_unescape(ext_text[k.end() : end].strip())
        return {
            "cef_version": int(m.group(1)),
            "device_vendor": _cef_unescape(m.group(2)),
            "device_product": _cef_unescape(m.group(3)),
            "device_version": _cef_unescape(m.group(4)),
            "signature_id": _cef_unescape(m.group(5)),
            "name": _cef_unescape(m.group(6)),
            "severity": _cef_unescape(m.group(7)),
            "extension": extension,
        }


class GELF(Format):
    name, label, group = "gelf", "Graylog GELF", CORE

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("timestamp", "timestamp"),
            Column("version", "string"),
            Column("host", "string"),
            Column("level", "integer"),
            Column("short_message", "string"),
            Column("full_message", "string"),
            Column("additional", "json"),
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        value = JsonLines().fields(record)
        if "short_message" not in value or "host" not in value:
            raise ParseError("a GELF message names its host and short_message")
        stamp = value.get("timestamp")
        return {
            "timestamp": None
            if stamp is None
            else datetime.fromtimestamp(float(stamp), tz=timezone.utc),
            "version": value.get("version"),
            "host": value["host"],
            "level": value.get("level"),
            "short_message": value["short_message"],
            "full_message": value.get("full_message"),
            "additional": {k[1:]: v for k, v in value.items() if k.startswith("_")} or None,
        }


# --- any other format: a regular expression ------------------------------------------------


def regex_format(pattern: str, record_start: str | None = None) -> RegexFormat:
    """A format given as a regular expression: its named groups are the columns, as text unless
    the source says otherwise; ``record_start`` joins following lines into a record."""
    try:
        compiled = re.compile(pattern, re.DOTALL)
    except re.error as exc:
        raise ValueError(f"the pattern is not a regular expression: {exc}") from exc
    names = list(compiled.groupindex)
    if not names:
        raise ValueError("the pattern names no group: (?P<name>...) gives a column")
    if record_start is not None:
        try:
            re.compile(record_start)
        except re.error as exc:
            raise ValueError(f"the record start is not a regular expression: {exc}") from exc
    return RegexFormat(
        "regex",
        "Regular expression",
        CORE,
        pattern,
        [Column(n, "string") for n in names],
        record_start=record_start,
        flags=re.DOTALL,
    )
