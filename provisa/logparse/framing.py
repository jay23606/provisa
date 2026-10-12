# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""A log's lines grouped into its records (REQ-1996). Without a record-start pattern each line is
a record; with one, a record is a line that matches it and every following line that does not
(a stack trace under its exception, the lines of a slow-query entry). Lines before the first
start are a record of their own, which a format may well refuse -- kept, not dropped."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator


def records(
    lines: Iterable[tuple[int, str]], start: re.Pattern[str] | None
) -> Iterator[tuple[int, str]]:
    """``(offset, text)`` per record, from ``(offset, line)`` with the line's ending removed; a
    record's offset is its first line's."""
    if start is None:
        yield from lines
        return
    held: list[str] = []
    held_at = 0
    for offset, line in lines:
        if start.match(line) and held:
            yield held_at, "\n".join(held)
            held = []
        if not held:
            held_at = offset
        held.append(line)
    if held:
        yield held_at, "\n".join(held)
