# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""The shared log-parser library (REQ-1996): the built-in formats by name, grouped as the source
form's format select shows them, and the regular-expression format a source defines."""

from __future__ import annotations

from provisa.logparse.base import COLUMN_TYPES, Column, FileContext, Format, ParseError
from provisa.logparse.formats import (
    CEF,
    CLF,
    COMBINED,
    GELF,
    MACOS_INSTALL,
    RFC3164,
    RFC5424,
    W3C,
    JsonLines,
    Logfmt,
    regex_format,
)
from provisa.logparse.framing import records

__all__ = [
    "COLUMN_TYPES",
    "Column",
    "FileContext",
    "Format",
    "ParseError",
    "BUILT_IN",
    "catalog",
    "format_for",
    "records",
]

BUILT_IN: dict[str, Format] = {
    f.name: f
    for f in (
        RFC3164,
        RFC5424,
        MACOS_INSTALL,
        CLF,
        COMBINED,
        JsonLines(),
        Logfmt(),
        W3C(),
        CEF(),
        GELF(),
    )
}


def catalog() -> list[dict[str, str | bool]]:
    """The formats a source may name, in their groups' order, the regular expression last."""
    out: list[dict[str, str | bool]] = [
        {"name": f.name, "label": f.label, "group": f.group, "pattern": False}
        for f in BUILT_IN.values()
    ]
    out.append({"name": "regex", "label": "Regular expression", "group": "Custom", "pattern": True})
    return out


def format_for(name: str, pattern: str | None = None, record_start: str | None = None) -> Format:
    """The format a source names; ``regex`` takes the source's pattern and record start."""
    if name == "regex":
        if not pattern:
            raise ValueError("the regex format needs a pattern")
        return regex_format(pattern, record_start)
    if name not in BUILT_IN:
        raise ValueError(
            f"no log format named {name!r}; the formats are {', '.join([*BUILT_IN, 'regex'])}"
        )
    if pattern or record_start:
        raise ValueError(f"the {name} format takes no pattern or record start")
    return BUILT_IN[name]
