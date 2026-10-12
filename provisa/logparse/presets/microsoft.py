# Copyright (c) 2026 Kenneth Stott
# Canary: 4ae3ecee-0e50-4037-8716-24ccd8d14543
#
# This source code is licensed under the Business Source License 1.1
"""Microsoft log presets (REQ-1996): IIS, Windows Firewall, Windows DNS debug, DHCP server audit,
Exchange message tracking, SQL Server ERRORLOG, Azure Storage analytics and Azure Monitor / Activity
Log exports, each in the form its Microsoft documentation gives. Windows writes its own logs
(Firewall, DNS, DHCP, ERRORLOG) in the server's local time: they are read in the zone of the file's
last write. IIS, Exchange and Azure write UTC."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.formats import W3C, RegexFormat
from provisa.logparse.presets._shared import JsonFormat, unwrap, utc

GROUP = "microsoft"


def _local(stamp: str, fmt: str, ctx: FileContext) -> datetime:
    """A local timestamp, in the zone of the file's last write."""
    try:
        return datetime.strptime(stamp, fmt).replace(tzinfo=ctx.mtime.tzinfo)
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc


# --- IIS ---------------------------------------------------------------------------------------


class IIS(W3C):
    """IIS logs in the W3C extended form IIS writes by default (UTC)."""

    name, label, group = "ms_iis", "Microsoft IIS log", GROUP


# --- Windows Firewall (pfirewall.log) ----------------------------------------------------------


class WindowsFirewall(W3C):
    """The Windows Defender Firewall log: W3C-like, its ``#Fields`` naming each file's columns, its
    date and time in the server's local time."""

    name, label, group = "ms_windows_firewall", "Windows Firewall log", GROUP

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        row = super().parse(record, ctx)
        if row.get("timestamp") is not None:
            row["timestamp"] = row["timestamp"].replace(tzinfo=ctx.mtime.tzinfo)
        return row


# --- Windows DNS server debug log --------------------------------------------------------------

_DNS_NAME = re.compile(r"\((\d+)\)")


def _dns_name(wire: str | None) -> str | None:
    """``(3)www(7)example(3)com(0)`` as ``www.example.com``."""
    if wire is None:
        return None
    return ".".join(p for p in _DNS_NAME.split(wire)[2::2] if p) or "."


def _dns(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": _local(f"{g['date']} {g['time']}", "%m/%d/%Y %I:%M:%S %p", ctx),
        "thread_id": g["thread"],
        "context": g["context"],
        "packet_id": g["packet"],
        "protocol": g["protocol"],
        "direction": "send" if g["direction"] == "Snd" else "receive",
        "remote_ip": g["remote_ip"],
        "xid": g["xid"],
        "response": g["response"] == "R",
        "opcode": g["opcode"],
        "flags_hex": g["flags_hex"],
        "flags": (g["flags"] or "").strip() or None,
        "rcode": g["rcode"],
        "question_type": g["qtype"],
        "question_name": _dns_name(g["qname"]),
    }


DNS_DEBUG = RegexFormat(
    "ms_dns_debug",
    "Windows DNS server debug log",
    GROUP,
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{4}) (?P<time>\d{1,2}:\d{2}:\d{2} [AP]M) (?P<thread>[0-9A-F]+) "
    r"(?P<context>PACKET)\s+(?P<packet>[0-9A-F]+) (?P<protocol>UDP|TCP) (?P<direction>Snd|Rcv) "
    r"(?P<remote_ip>\S+)\s+(?P<xid>[0-9a-f]{4}) (?P<response>R| ) (?P<opcode>\S) "
    r"\[(?P<flags_hex>[0-9A-F]{4})\s+(?P<flags>[ATDR ]*?)\s*(?P<rcode>[A-Z]+)\]\s+"
    r"(?P<qtype>\S+)\s+(?P<qname>\S+)\s*$",
    [
        Column("timestamp", "timestamp"),
        Column("thread_id", "string"),
        Column("context", "string"),
        Column("packet_id", "string"),
        Column("protocol", "string"),
        Column("direction", "string"),
        Column("remote_ip", "string"),
        Column("xid", "string"),
        Column("response", "boolean"),
        Column("opcode", "string"),
        Column("flags_hex", "string"),
        Column("flags", "string"),
        Column("rcode", "string"),
        Column("question_type", "string"),
        Column("question_name", "string"),
    ],
    _dns,
)

# --- DHCP server audit log ---------------------------------------------------------------------

_DHCP_FIELDS = [
    "event_id",
    "date",
    "time",
    "description",
    "ip_address",
    "host_name",
    "mac_address",
    "user_name",
    "transaction_id",
    "q_result",
    "probation_time",
    "correlation_id",
    "dhcid",
    "vendor_class_hex",
    "vendor_class_ascii",
    "user_class_hex",
    "user_class_ascii",
    "relay_agent_information",
    "dns_reg_error",
]
_DHCP_RECORD = re.compile(r"^\d+,")


class DhcpAudit(Format):
    """The DHCP server audit log (DhcpSrvLog-*.log): comma-separated events after a preamble that
    explains the event IDs and a header line; the date (MM/DD/YY) and time are the server's local
    time. A preamble or header line is not an event, and is refused as one."""

    name, label, group = "ms_dhcp_audit", "Windows DHCP server audit log", GROUP

    def columns(self, preview: list[str]) -> list[Column]:
        cols = [Column("timestamp", "timestamp")]
        for f in _DHCP_FIELDS:
            if f in ("date", "time"):
                continue
            cols.append(
                Column(f, "integer" if f in ("event_id", "q_result", "dns_reg_error") else "string")
            )
        return [*cols, Column("extra", "json")]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        if not _DHCP_RECORD.match(record):
            raise ParseError(f"not an event of the {self.label}")
        values = next(csv.reader([record]))
        named = {f: (v.strip() or None) for f, v in zip(_DHCP_FIELDS, values)}
        row: dict[str, Any] = {
            "timestamp": _local(
                f"{named.pop('date')} {named.pop('time')}", "%m/%d/%y %H:%M:%S", ctx
            )
        }
        row.update(named)
        return row


# --- Exchange message tracking -----------------------------------------------------------------


class ExchangeTracking(W3C):
    """Exchange message tracking logs: a ``#Fields`` header names the comma-separated columns;
    values that hold a comma are quoted; ``date-time`` is UTC, ISO 8601."""

    name, label, group = "ms_exchange_tracking", "Microsoft Exchange message tracking log", GROUP

    def _header_fields(self, preview: list[str]) -> list[str]:
        for line in preview:
            if line.startswith("#Fields:"):
                return line[len("#Fields:") :].strip().split(",")
        return []

    def on_header(self, line: str, ctx: FileContext) -> None:
        name, _, value = line[1:].partition(":")
        if name == "Fields":
            ctx.fields = value.strip().split(",")
        else:
            ctx.directives[name] = value.strip()

    def _split(self, line: str) -> list[str]:
        return next(csv.reader([line]))

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("timestamp", "timestamp") if c.name == "date_time" else c
            for c in super().columns(preview)
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        row = super().parse(record, ctx)
        if "date_time" in row:
            row["timestamp"] = utc(row.pop("date_time"))
        return {k: (None if v == "" else v) for k, v in row.items()}


# --- SQL Server ERRORLOG -----------------------------------------------------------------------


def _errorlog(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": _local(g["timestamp"] or "", "%Y-%m-%d %H:%M:%S.%f", ctx),
        "source": g["source"],
        "message": g["message"],
    }


SQLSERVER_ERRORLOG = RegexFormat(
    "ms_sqlserver_errorlog",
    "SQL Server error log (ERRORLOG)",
    GROUP,
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{2}) (?P<source>\S+)\s+(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("source", "string"),
        Column("message", "string"),
    ],
    _errorlog,
    record_start=r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{2} ",
    flags=re.DOTALL,
)

# --- Azure Storage analytics logs --------------------------------------------------------------

_AZURE_STORAGE_FIELDS = [
    "version_number",
    "request_start_time",
    "operation_type",
    "request_status",
    "http_status_code",
    "end_to_end_latency_ms",
    "server_latency_ms",
    "authentication_type",
    "requester_account_name",
    "owner_account_name",
    "service_type",
    "request_url",
    "requested_object_key",
    "request_id_header",
    "operation_count",
    "requester_ip_address",
    "request_version_header",
    "request_header_size",
    "request_packet_size",
    "response_header_size",
    "response_packet_size",
    "request_content_length",
    "request_md5",
    "server_md5",
    "etag_identifier",
    "last_modified_time",
    "conditions_used",
    "user_agent_header",
    "referrer_header",
    "client_request_id",
    # version 2.0
    "user_object_id",
    "tenant_id",
    "application_id",
    "audience",
    "issuer",
    "user_principal_name",
    "reserved_field",
    "authorization_detail",
]
_AZURE_STORAGE_INTEGERS = {
    "http_status_code",
    "end_to_end_latency_ms",
    "server_latency_ms",
    "operation_count",
    "request_header_size",
    "request_packet_size",
    "response_header_size",
    "response_packet_size",
    "request_content_length",
}


class AzureStorage(Format):
    """Azure Storage analytics (classic) logs: semicolon-separated fields, quoted where they may
    hold one; version 1.0 has 30 fields, version 2.0 eight more."""

    name, label, group = "azure_storage_analytics", "Azure Storage analytics log", GROUP

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column(
                f,
                "timestamp"
                if f == "request_start_time"
                else "integer"
                if f in _AZURE_STORAGE_INTEGERS
                else "string",
            )
            for f in _AZURE_STORAGE_FIELDS
        ] + [Column("extra", "json")]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        values = next(csv.reader(io.StringIO(record), delimiter=";"))
        if len(values) < 30:
            raise ParseError(f"{len(values)} fields, fewer than the 30 of the {self.label}")
        # A version 1.0 line has none of the version 2.0 fields.
        padded = values + [""] * (len(_AZURE_STORAGE_FIELDS) - len(values))
        row: dict[str, Any] = {
            f: (unwrap(v) if v != "" else None) for f, v in zip(_AZURE_STORAGE_FIELDS, padded)
        }
        row["request_start_time"] = utc(row["request_start_time"])
        return row


# --- Azure Monitor resource logs and Activity Log exports --------------------------------------


class AzureMonitor(JsonFormat):
    """Azure Monitor resource logs and Activity Log exports to storage: one JSON record a line, or
    an export document ``{"records": [...]}``, each record a row."""

    def __init__(self) -> None:
        super().__init__(
            "azure_monitor",
            "Azure Monitor / Activity Log export",
            GROUP,
            [
                (Column("time", "timestamp"), "time"),
                (Column("resource_id", "string"), "resourceId"),
                (Column("operation_name", "string"), "operationName"),
                (Column("category", "string"), "category"),
                (Column("result_type", "string"), "resultType"),
                (Column("result_signature", "string"), "resultSignature"),
                (Column("duration_ms", "integer"), "durationMs"),
                (Column("caller_ip_address", "string"), "callerIpAddress"),
                (Column("correlation_id", "string"), "correlationId"),
                (Column("level", "string"), "level"),
                (Column("location", "string"), "location"),
                (Column("identity", "json"), "identity"),
                (Column("properties", "json"), "properties"),
            ],
            lambda row, doc: {**row, "time": utc(row["time"])},
        )
        self.record_start = re.compile(r"\{")

    def parse_many(self, record: str, ctx: FileContext) -> list[dict[str, Any]]:
        doc = self.load(record)
        if "records" not in doc:
            return [self.row(doc)]
        items = doc["records"]
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise ParseError(f"the records of an {self.label} document are not a list of objects")
        return [self.row(item) for item in items]


# --- Windows Event Log (.evtx) ----------------------------------------------------------------

_EVT = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def _element(node: Any) -> Any:
    """An XML element as JSON: its attributes and children by name, or its text."""
    children = list(node)
    if not children and not node.attrib:
        return node.text
    out: dict[str, Any] = {k: v for k, v in node.attrib.items() if not k.startswith("{")}
    for child in children:
        name = child.tag.rsplit("}", 1)[-1]
        value = _element(child)
        if name in out:
            out[name] = (out[name] if isinstance(out[name], list) else [out[name]]) + [value]
        else:
            out[name] = value
    return out


class WindowsEvtx(Format):
    """Windows Event Log files (.evtx): binary, read record by record with python-evtx, each
    record's XML a row. A record's offset is its own in the file, so a growing log is read on
    from the record it reached."""

    name, label, group = "windows_evtx", "Windows Event Log (.evtx)", GROUP
    frames_bytes = True

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("time_created", "timestamp"),
            Column("event_id", "integer"),
            Column("provider", "string"),
            Column("provider_guid", "string"),
            Column("level", "integer"),
            Column("task", "integer"),
            Column("opcode", "integer"),
            Column("keywords", "string"),
            Column("event_record_id", "integer"),
            Column("process_id", "integer"),
            Column("thread_id", "integer"),
            Column("channel", "string"),
            Column("computer", "string"),
            Column("user_id", "string"),
            Column("activity_id", "string"),
            Column("event_data", "json"),
            Column("user_data", "json"),
            Column("extra", "json"),
        ]

    def frame(self, path: str, stream: Any, start: int, whole: bool) -> Any:
        from Evtx.Evtx import Evtx

        with Evtx(path) as log:
            for record in log.records():
                offset = record.offset()
                if offset < start:
                    continue
                yield offset, record.xml(), offset + record.size()

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        from defusedxml.ElementTree import ParseError as XmlError
        from defusedxml.ElementTree import fromstring

        try:
            event = fromstring(record)
        except XmlError as exc:
            raise ParseError(f"not an event record: {exc}") from exc
        system = event.find(f"{_EVT}System")
        if system is None:
            raise ParseError("an event record without its System element")

        def text(tag: str) -> str | None:
            node = system.find(f"{_EVT}{tag}")
            return None if node is None or not node.text else node.text

        def attr(tag: str, name: str) -> str | None:
            node = system.find(f"{_EVT}{tag}")
            value = None if node is None else node.get(name)
            return value or None

        event_data = event.find(f"{_EVT}EventData")
        data: Any = None
        if event_data is not None:
            items = [(d.get("Name"), d.text) for d in event_data.findall(f"{_EVT}Data")]
            named = all(name for name, _ in items)
            data = {name: value for name, value in items} if named else [v for _, v in items]
        user_data = event.find(f"{_EVT}UserData")
        stamp = attr("TimeCreated", "SystemTime")
        return {
            "time_created": utc(stamp),
            "event_id": text("EventID"),
            "provider": attr("Provider", "Name"),
            "provider_guid": attr("Provider", "Guid"),
            "level": text("Level"),
            "task": text("Task"),
            "opcode": text("Opcode"),
            "keywords": text("Keywords"),
            "event_record_id": text("EventRecordID"),
            "process_id": attr("Execution", "ProcessID"),
            "thread_id": attr("Execution", "ThreadID"),
            "channel": text("Channel"),
            "computer": text("Computer"),
            "user_id": attr("Security", "UserID"),
            "activity_id": attr("Correlation", "ActivityID"),
            "event_data": data,
            "user_data": None if user_data is None else _element(user_data),
        }


PRESETS: list[Format] = [
    IIS(),
    WindowsFirewall(),
    DNS_DEBUG,
    DhcpAudit(),
    ExchangeTracking(),
    SQLSERVER_ERRORLOG,
    AzureStorage(),
    AzureMonitor(),
    WindowsEvtx(),
]
