# Copyright (c) 2026 Kenneth Stott
# Canary: 7b0249b8-36d4-4692-985e-88aea3a004c9
#
# This source code is licensed under the Business Source License 1.1
"""A Logs source's settings, as its mapping holds them (REQ-1996): the glob of the files it
reads, the format their records are in, and for a regular-expression format its pattern and
the pattern a record's first line matches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from provisa.logparse import Format, format_for


class InvalidLogsSource(ValueError):
    """The settings cannot be a Logs source; the reason is the setup's own words."""


@dataclass(frozen=True)
class LogsSettings:
    glob: str
    format: str
    pattern: str | None = None
    record_start: str | None = None

    def parser(self) -> Format:
        return format_for(self.format, self.pattern, self.record_start)


def _text(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InvalidLogsSource(f"{key} must be text, not {type(value).__name__}")
    return value


def parse(mapping: dict[str, Any]) -> LogsSettings:
    unknown = sorted(set(mapping) - {"glob", "format", "pattern", "record_start"})
    if unknown:
        raise InvalidLogsSource(f"a Logs source has no setting {', '.join(unknown)}")
    glob = _text(mapping, "glob")
    if glob is None:
        raise InvalidLogsSource(
            "name the files to read: a path or a glob, such as /var/log/system.log*"
        )
    name = _text(mapping, "format")
    if name is None:
        raise InvalidLogsSource("choose the format the files are in")
    settings = LogsSettings(glob, name, _text(mapping, "pattern"), _text(mapping, "record_start"))
    try:
        settings.parser()
    except ValueError as exc:
        raise InvalidLogsSource(str(exc)) from exc
    return settings
