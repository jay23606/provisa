# Copyright (c) 2026 Kenneth Stott
# Canary: ee79e4c9-a3c5-41d2-a1fd-e17c083b82bd
#
# This source code is licensed under the Business Source License 1.1
"""Readers the preset families share (REQ-1996): a log of space-separated fields, some quoted or
bracketed, read by position; and a JSON record with known fields, read by key path. Not a family:
it lists no presets of its own."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from provisa.logparse.base import Column, FileContext, Format, ParseError

PRESETS: list[Format] = []

#: One field: a run of quoted strings, bracketed text and other non-space characters.
_TOKEN = re.compile(r'(?:"(?:[^"\\]|\\.)*"|\[[^\]]*\]|[^\s"\[])+')


def tokens(line: str) -> list[str]:
    """A line's fields: split at spaces, except inside double quotes or square brackets."""
    return _TOKEN.findall(line)


def unwrap(token: str) -> str | None:
    """A field's value: one quoted string or bracketed text without its quotes or brackets, its
    escapes read; ``-`` (or ``"-"``) is no value."""
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"' and _TOKEN.fullmatch(token):
        inner = token[1:-1]
        if '"' not in inner.replace('\\"', ""):
            token = inner.replace('\\"', '"').replace("\\\\", "\\")
    elif len(token) >= 2 and token[0] == "[" and token[-1] == "]":
        token = token[1:-1]
    return None if token in ("-", "") else token


def utc(stamp: str | None, fmt: str | None = None) -> datetime | None:
    """A timestamp read in UTC: ISO 8601 (with or without an offset), or ``fmt`` by strptime."""
    if stamp is None:
        return None
    try:
        value = (
            datetime.strptime(stamp, fmt)
            if fmt
            else datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def epoch(value: Any, millis: bool = False) -> datetime | None:
    """Seconds (or milliseconds) since 1970 as a UTC timestamp."""
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ParseError(f"not an epoch time: {value!r}") from exc
    return datetime.fromtimestamp(number / 1000 if millis else number, tz=timezone.utc)


def host_port(value: str | None) -> tuple[str | None, int | None]:
    """``ip:port`` (an IPv6 address keeps its colons) as its address and port."""
    if value is None:
        return None, None
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit():
        return value, None
    return host.strip("[]"), int(port)


_REQUEST = re.compile(r"^(?P<method>\S+) (?P<url>\S+)(?: (?P<protocol>\S+))?$")


def request_parts(request: str | None) -> dict[str, str | None]:
    """An HTTP request line as its method, URL and protocol; a line not in that form, none."""
    m = _REQUEST.match(request or "")
    if m is None:
        return {"method": None, "url": None, "protocol": None}
    return m.groupdict()


class TokenFormat(Format):
    """A log whose fields are space-separated, in a fixed order (some quoted, some bracketed),
    read by position. A record shorter than ``required`` fields is refused; fields past the
    known ones (a newer version's) are kept, in order, under ``trailing``. ``convert`` types the
    fields and derives columns."""

    def __init__(
        self,
        name: str,
        label: str,
        group: str,
        fields: list[str],
        columns: list[Column],
        convert: Callable[[dict[str, str | None], FileContext], dict[str, Any]],
        required: int | None = None,
    ) -> None:
        self.name, self.label, self.group = name, label, group
        self.fields = fields
        self._columns = columns
        self._convert = convert
        self.required = len(fields) if required is None else required

    def columns(self, preview: list[str]) -> list[Column]:
        return [*self._columns, Column("extra", "json")]

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        found = tokens(record.strip())
        if len(found) < self.required:
            raise ParseError(
                f"{len(found)} fields, fewer than the {self.required} of the {self.label} form"
            )
        named = {f: unwrap(t) for f, t in zip(self.fields, found)}
        for f in self.fields[len(found) :]:
            named[f] = None
        row = self._convert(named, ctx)
        if len(found) > len(self.fields):
            row["trailing"] = [unwrap(t) for t in found[len(self.fields) :]]
        return row


def path(value: Any, keys: str) -> Any:
    """The value at a dotted key path of nested objects; a missing key is no value."""
    for key in keys.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


class JsonFormat(Format):
    """A JSON record with known fields: each column is the value at its key path; ``convert``
    may type or derive them. The record's other top-level keys are kept in ``extra``."""

    def __init__(
        self,
        name: str,
        label: str,
        group: str,
        fields: list[tuple[Column, str]],
        convert: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.name, self.label, self.group = name, label, group
        self.fields = fields
        self._convert = convert

    def columns(self, preview: list[str]) -> list[Column]:
        return [c for c, _ in self.fields] + [Column("extra", "json")]

    def load(self, record: str) -> dict[str, Any]:
        try:
            value = json.loads(record)
        except json.JSONDecodeError as exc:
            raise ParseError(f"not JSON: {exc.msg} at column {exc.colno}") from exc
        if not isinstance(value, dict):
            raise ParseError(f"a JSON {type(value).__name__}, not an object")
        return value

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        return self.row(self.load(record))

    def row(self, doc: dict[str, Any]) -> dict[str, Any]:
        """One JSON object as a row: the known fields by key path, the others kept."""
        row = {c.name: path(doc, keys) for c, keys in self.fields}
        if self._convert:
            row = self._convert(row, doc)
        taken = {keys.split(".")[0] for _, keys in self.fields}
        for key, value in doc.items():
            if key not in taken and key not in row:
                row[key] = value
        return row


class BatchJsonFormat(JsonFormat):
    """A JSON document that is a batch of entries under one key (a CloudTrail file's
    ``Records``, an Azure export's ``records``): each entry is a row, read as a
    :class:`JsonFormat` reads one object. A record is a document: a line that starts with ``{``
    starts the next one, so a document written over several lines is read whole."""

    def __init__(
        self,
        name: str,
        label: str,
        group: str,
        entries: str,
        fields: list[tuple[Column, str]],
        convert: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(name, label, group, fields, convert)
        self.entries = entries
        self.record_start = re.compile(r"\{")

    def parse_many(self, record: str, ctx: FileContext) -> list[dict[str, Any]]:
        doc = self.load(record)
        items = doc.get(self.entries)
        if not isinstance(items, list):
            raise ParseError(f"no {self.entries} list in the {self.label} document")
        rows = []
        for item in items:
            if not isinstance(item, dict):
                raise ParseError(f"a {self.entries} entry that is not an object")
            rows.append(self.row(item))
        return rows

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        raise ParseError(f"a {self.label} document is a batch of entries, read by parse_many")
