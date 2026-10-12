# Copyright (c) 2026 Kenneth Stott
# Canary: dba9704f-81d3-402a-baa7-f7c5e8219b5f
#
# This source code is licensed under the Business Source License 1.1
"""What a log format is (REQ-1996): the columns it gives a table, and how one record of a log
becomes a row of them. Shared, with no Provisa imports, so any source that reads log text uses it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ColumnType = Literal["string", "integer", "float", "boolean", "timestamp", "json"]
COLUMN_TYPES: tuple[str, ...] = ("string", "integer", "float", "boolean", "timestamp", "json")


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


class ParseError(ValueError):
    """A record the format cannot read; its reason is kept beside the record's raw text."""


@dataclass
class FileContext:
    """What a format may know of the file a record is in: when it was last written (a BSD syslog
    line carries no year), and the columns its header declared (W3C, CloudFront, Zeek)."""

    mtime: datetime
    fields: list[str] | None = None
    directives: dict[str, str] = field(default_factory=dict)


class Format:
    """One record in, one row out. A format with ``record_start`` joins the lines after a start
    into its record (a stack trace, a slow-query entry); one with ``header_prefix`` reads the
    lines that start with it as the file's directives, not as records."""

    name: str
    label: str
    group: str
    record_start: re.Pattern[str] | None = None
    header_prefix: str | None = None

    def columns(self, preview: list[str]) -> list[Column]:
        raise NotImplementedError

    def on_header(self, line: str, ctx: FileContext) -> None:
        raise NotImplementedError(f"{self.name} has no header")

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        raise NotImplementedError
