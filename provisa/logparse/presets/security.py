# Copyright (c) 2026 Kenneth Stott
# Canary: df6e435b-744d-4c27-845d-e5f9bd576f02
#
# This source code is licensed under the Business Source License 1.1
"""Network security monitor log presets (REQ-1996): Zeek logs in their tab-separated form (the
header names and types each file's columns) and as JSON, Suricata's EVE JSON, and Snort's fast
alert format, each in the form its documentation gives."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from provisa.logparse.base import Column, ColumnType, FileContext, Format, ParseError
from provisa.logparse.formats import W3C, RegexFormat, _column_name
from provisa.logparse.presets._shared import JsonFormat, epoch, host_port, utc

GROUP = "security"

# --- Zeek, tab-separated -----------------------------------------------------------------------

#: Zeek's field types and the column types they read as.
_ZEEK_TYPES: dict[str, ColumnType] = {
    "time": "timestamp",
    "interval": "float",
    "double": "float",
    "count": "integer",
    "int": "integer",
    "port": "integer",
    "bool": "boolean",
}


def _zeek_column_type(zeek_type: str) -> ColumnType:
    """The column type a Zeek field type reads as: a set or vector is a JSON list."""
    if zeek_type.startswith(("set[", "vector[")):
        return "json"
    return _ZEEK_TYPES.get(zeek_type, "string")


class ZeekTsv(W3C):
    """A Zeek log in its default tab-separated form: ``#fields`` names each file's columns and
    ``#types`` types them; ``#unset_field`` (``-``) is no value and ``#empty_field``
    (``(empty)``) an empty one; ``ts`` is epoch seconds."""

    name, label, group = "zeek_tsv", "Zeek log (tab-separated)", GROUP
    separator = "\t"

    def _header_fields(self, preview: list[str]) -> list[str]:
        for line in preview:
            if line.startswith("#fields"):
                return line.split("\t")[1:]
        return []

    def columns(self, preview: list[str]) -> list[Column]:
        fields = self._header_fields(preview)
        types: list[str] = []
        for line in preview:
            if line.startswith("#types"):
                types = line.split("\t")[1:]
        if len(types) != len(fields):
            raise ParseError("the #types header does not type every one of the #fields")
        return [Column(_column_name(f), _zeek_column_type(t)) for f, t in zip(fields, types)] + [
            Column("extra", "json")
        ]

    def on_header(self, line: str, ctx: FileContext) -> None:
        name, _, value = line[1:].partition("\t")
        if name == "fields":
            ctx.fields = value.split("\t")
        else:
            ctx.directives[name] = value

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        if not ctx.fields:
            raise ParseError("no #fields header before this line")
        values = record.split("\t")
        if len(values) != len(ctx.fields):
            raise ParseError(f"{len(values)} values for the header's {len(ctx.fields)} fields")
        unset = ctx.directives.get("unset_field", "-")
        empty = ctx.directives.get("empty_field", "(empty)")
        set_separator = ctx.directives.get("set_separator", ",")
        types = ctx.directives.get("types", "").split("\t")
        row: dict[str, Any] = {}
        for i, (field, value) in enumerate(zip(ctx.fields, values)):
            kind = types[i] if i < len(types) else ""
            if value == unset:
                parsed: Any = None
            elif value == empty:
                parsed = [] if kind.startswith(("set[", "vector[")) else ""
            elif kind.startswith(("set[", "vector[")):
                parsed = value.split(set_separator)
            elif kind == "time":
                parsed = epoch(value)
            elif kind == "bool":
                parsed = value == "T"
            else:
                parsed = value
            row[_column_name(field)] = parsed
        return row


# --- Zeek, JSON --------------------------------------------------------------------------------


class ZeekJson(Format):
    """A Zeek log written as JSON (LogAscii::use_json): one object a line, its keys the log's
    fields; ``ts`` (and any other time) is epoch seconds or ISO 8601, as configured."""

    name, label, group = "zeek_json", "Zeek log (JSON)", GROUP

    def columns(self, preview: list[str]) -> list[Column]:
        from provisa.logparse.coltypes import infer_type

        seen: dict[str, list[Any]] = {}
        for line in preview:
            try:
                doc = self._load(line)
            except ParseError:
                continue
            for k, v in doc.items():
                seen.setdefault(k, []).append(v)
        return [
            Column(_column_name(k), "timestamp" if k == "ts" else infer_type(v))
            for k, v in seen.items()
        ] + [Column("extra", "json")]

    def _load(self, record: str) -> dict[str, Any]:
        try:
            doc = json.loads(record)
        except json.JSONDecodeError as exc:
            raise ParseError(f"not JSON: {exc.msg} at column {exc.colno}") from exc
        if not isinstance(doc, dict):
            raise ParseError(f"a JSON {type(doc).__name__}, not an object")
        return doc

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        doc = self._load(record)
        row = {_column_name(k): v for k, v in doc.items()}
        if "ts" in row:
            ts = row["ts"]
            row["ts"] = epoch(ts) if isinstance(ts, (int, float)) else utc(ts)
        return row


# --- Suricata EVE JSON -------------------------------------------------------------------------


def _suricata_time(stamp: str | None) -> datetime | None:
    """EVE's timestamp, ``2023-05-11T08:15:23.456789+0000``: an offset without a colon."""
    if stamp is None:
        return None
    if len(stamp) > 5 and stamp[-5] in "+-" and stamp[-4:].isdigit():
        stamp = f"{stamp[:-2]}:{stamp[-2:]}"
    return utc(stamp)


SURICATA = JsonFormat(
    "suricata_eve",
    "Suricata EVE JSON",
    GROUP,
    [
        (Column("timestamp", "timestamp"), "timestamp"),
        (Column("event_type", "string"), "event_type"),
        (Column("flow_id", "integer"), "flow_id"),
        (Column("in_iface", "string"), "in_iface"),
        (Column("src_ip", "string"), "src_ip"),
        (Column("src_port", "integer"), "src_port"),
        (Column("dest_ip", "string"), "dest_ip"),
        (Column("dest_port", "integer"), "dest_port"),
        (Column("proto", "string"), "proto"),
        (Column("app_proto", "string"), "app_proto"),
        (Column("alert_action", "string"), "alert.action"),
        (Column("alert_signature_id", "integer"), "alert.signature_id"),
        (Column("alert_signature", "string"), "alert.signature"),
        (Column("alert_category", "string"), "alert.category"),
        (Column("alert_severity", "integer"), "alert.severity"),
        (Column("alert", "json"), "alert"),
        (Column("http", "json"), "http"),
        (Column("dns", "json"), "dns"),
        (Column("tls", "json"), "tls"),
        (Column("flow", "json"), "flow"),
    ],
    lambda row, doc: {**row, "timestamp": _suricata_time(row["timestamp"])},
)

# --- Snort fast alerts -------------------------------------------------------------------------


def _snort(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    stamp = g["stamp"] or ""
    if stamp.count("/") == 2:  # snort -y writes the year
        fmt = "%m/%d/%y-%H:%M:%S.%f"
        text = stamp
    else:
        month = int(stamp[:2])
        year = ctx.mtime.year - (1 if month > ctx.mtime.month else 0)
        fmt, text = "%Y/%m/%d-%H:%M:%S.%f", f"{year}/{stamp}"
    try:
        when = datetime.strptime(text, fmt).replace(tzinfo=ctx.mtime.tzinfo)
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc
    src_ip, src_port = host_port(g["src"])
    dst_ip, dst_port = host_port(g["dst"])
    return {
        "timestamp": when,
        "generator_id": g["gid"],
        "signature_id": g["sid"],
        "revision": g["rev"],
        "message": g["msg"],
        "classification": g["classification"],
        "priority": g["priority"],
        "protocol": g["proto"],
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
    }


SNORT_FAST = RegexFormat(
    "snort_fast",
    "Snort alert (fast)",
    GROUP,
    r"^(?P<stamp>\d{2}/\d{2}(?:/\d{2})?-\d{2}:\d{2}:\d{2}\.\d+)\s+\[\*\*\] "
    r"\[(?P<gid>\d+):(?P<sid>\d+):(?P<rev>\d+)\] (?P<msg>.*?) \[\*\*\]"
    r"(?: \[Classification: (?P<classification>[^\]]*)\])?(?: \[Priority: (?P<priority>\d+)\])?"
    r" \{(?P<proto>[^}]+)\} (?P<src>\S+) -> (?P<dst>\S+)\s*$",
    [
        Column("timestamp", "timestamp"),
        Column("generator_id", "integer"),
        Column("signature_id", "integer"),
        Column("revision", "integer"),
        Column("message", "string"),
        Column("classification", "string"),
        Column("priority", "integer"),
        Column("protocol", "string"),
        Column("src_ip", "string"),
        Column("src_port", "integer"),
        Column("dst_ip", "string"),
        Column("dst_port", "integer"),
    ],
    _snort,
)

PRESETS: list[Format] = [ZeekTsv(), ZeekJson(), SURICATA, SNORT_FAST]
