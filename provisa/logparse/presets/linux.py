# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""Container and Linux log presets (REQ-1996): Kubernetes container logs in the CRI format (a long
line written in parts joined into one), the systemd journal as ``journalctl -o json`` exports it,
the Linux audit log (auditd) and the kernel ring buffer (dmesg), each in the form its documentation
gives."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from datetime import datetime
from typing import Any, BinaryIO

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.formats import RegexFormat
from provisa.logparse.presets._shared import JsonFormat, epoch, utc

GROUP = "linux"

# --- Kubernetes CRI container logs -------------------------------------------------------------

_CRI = re.compile(
    r"^(?P<time>\S+) (?P<stream>stdout|stderr) (?P<tag>[PF])(?::\S*)? ?(?P<message>.*)$"
)


class KubernetesCri(Format):
    """Kubernetes container logs (/var/log/pods, /var/log/containers) in the CRI format:
    ``<time> <stream> <P|F> <text>``. A line the runtime split is written as partial (P) parts and
    a final (F) one: the parts and the final are one record, its time the first part's. A final
    part not yet written is left for the next read."""

    name, label, group = "kubernetes_cri", "Kubernetes container log (CRI)", GROUP
    frames_bytes = True

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("timestamp", "timestamp"),
            Column("stream", "string"),
            Column("parts", "integer"),
            Column("message", "string"),
            Column("extra", "json"),
        ]

    def frame(
        self, path: str, stream: BinaryIO, start: int, whole: bool
    ) -> Iterator[tuple[int, str, int]]:
        stream.seek(start)
        offset = start
        held: list[str] = []
        held_at = start
        while True:
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b"\n") and not whole:
                break  # a line still being written
            end = offset + len(line)
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if not held:
                held_at = offset
            held.append(text)
            m = _CRI.match(text)
            if m is None or m.group("tag") == "F":
                yield held_at, "\n".join(held), end
                held = []
            offset = end
        if held and whole:
            yield held_at, "\n".join(held), offset

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        parts = []
        for line in record.split("\n"):
            m = _CRI.match(line)
            if m is None:
                raise ParseError(f"not in the {self.label} form")
            parts.append(m)
        return {
            "timestamp": utc(parts[0].group("time")),
            "stream": parts[0].group("stream"),
            "parts": len(parts),
            "message": "".join(p.group("message") for p in parts),
        }


# --- systemd journal (journalctl -o json) ------------------------------------------------------

JOURNALD = JsonFormat(
    "journald_json",
    "systemd journal (journalctl -o json)",
    GROUP,
    [
        (Column("timestamp", "timestamp"), "__REALTIME_TIMESTAMP"),
        (Column("hostname", "string"), "_HOSTNAME"),
        (Column("priority", "integer"), "PRIORITY"),
        (Column("syslog_identifier", "string"), "SYSLOG_IDENTIFIER"),
        (Column("syslog_facility", "integer"), "SYSLOG_FACILITY"),
        (Column("pid", "integer"), "_PID"),
        (Column("uid", "integer"), "_UID"),
        (Column("comm", "string"), "_COMM"),
        (Column("exe", "string"), "_EXE"),
        (Column("systemd_unit", "string"), "_SYSTEMD_UNIT"),
        (Column("transport", "string"), "_TRANSPORT"),
        (Column("boot_id", "string"), "_BOOT_ID"),
        (Column("message", "string"), "MESSAGE"),
        (Column("cursor", "string"), "__CURSOR"),
    ],
    # The realtime timestamp is microseconds since 1970, written as a string.
    lambda row, doc: {**row, "timestamp": epoch(int(row["timestamp"]) / 1_000_000)},
)

# --- Linux audit log (auditd) ------------------------------------------------------------------

_AUDIT = re.compile(
    r"^(?:node=(?P<node>\S+) )?type=(?P<type>\S+) msg=audit\((?P<time>\d+\.\d+):(?P<serial>\d+)\): ?"
    r"(?P<fields>.*)$"
)


class Auditd(Format):
    """The Linux audit log (/var/log/audit/audit.log): ``type=... msg=audit(<time>:<serial>):``
    then the record's key=value fields. The records of one event share its time and serial."""

    name, label, group = "linux_auditd", "Linux audit log (auditd)", GROUP

    def columns(self, preview: list[str]) -> list[Column]:
        return [
            Column("timestamp", "timestamp"),
            Column("serial", "integer"),
            Column("node", "string"),
            Column("type", "string"),
            Column("fields", "json"),
            Column("extra", "json"),
        ]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        m = _AUDIT.match(record)
        if m is None:
            raise ParseError(f"not in the {self.label} form")
        fields: dict[str, str] = {}
        body = m.group("fields")
        # The kernel and user-space parts of a USER_* record are split by a GS character, and its
        # msg='...' holds further pairs: both are read as pairs of their own.
        body = body.replace("\x1d", " ").replace("msg='", "").rstrip("'")
        try:
            pairs = shlex.split(body)
        except ValueError as exc:
            raise ParseError(f"fields not in key=value form: {exc}") from exc
        for pair in pairs:
            key, sep, value = pair.partition("=")
            if sep:
                fields[key] = value
        return {
            "timestamp": epoch(m.group("time")),
            "serial": m.group("serial"),
            "node": m.group("node"),
            "type": m.group("type"),
            "fields": fields,
        }


# --- Kernel ring buffer (dmesg) ----------------------------------------------------------------


def _dmesg(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    clock = g["clock"]
    when: datetime | None = None
    uptime: str | None = None
    if clock and clock.strip().replace(".", "", 1).isdigit():
        uptime = clock.strip()
    elif clock:
        # dmesg -T writes the wall-clock time, in the machine's local time.
        try:
            when = datetime.strptime(clock, "%a %b %d %H:%M:%S %Y").replace(tzinfo=ctx.mtime.tzinfo)
        except ValueError as exc:
            raise ParseError(f"not a timestamp: {clock!r}") from exc
    return {
        "timestamp": when,
        "uptime_s": uptime,
        "facility": g["facility"],
        "level": g["level"],
        "message": g["message"],
    }


DMESG = RegexFormat(
    "linux_dmesg",
    "Kernel ring buffer (dmesg)",
    GROUP,
    # dmesg -x prefixes facility:level; the clock is seconds since boot, or a date with -T.
    r"^(?:(?P<facility>[a-z]+)\s*:(?P<level>[a-z]+)\s*: )?\[(?P<clock>[^\]]+)\] (?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("uptime_s", "float"),
        Column("facility", "string"),
        Column("level", "string"),
        Column("message", "string"),
    ],
    _dmesg,
)

PRESETS: list[Format] = [KubernetesCri(), JOURNALD, Auditd(), DMESG]
