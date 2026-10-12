# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""What a Logs source's files hold before it is saved (REQ-1996): the files its glob matches,
the columns its format gives them -- worked out from their first lines for a format whose
records name their own fields -- and the first rows as they would land."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from provisa.core import settings_registry
from provisa.logs import LANDED_AT, META_COLUMNS
from provisa.logs.files import IR_TYPE, Table, identify, matched, read_file
from provisa.logs.files import preview as first_lines
from provisa.logs.roots import checked_glob
from provisa.logs.settings import LogsSettings


def columns(settings: LogsSettings) -> list[tuple[str, str]]:
    """The table's columns, as (name, IR type): the row's own, its format's, and its landing
    stamp. A format column named as one of the row's own is the row's."""
    glob = checked_glob(settings.glob)
    lines = first_lines(glob, int(settings_registry.value("logs.preview_lines")))
    own = {name for name, _ in META_COLUMNS} | {LANDED_AT}
    parsed = [
        (c.name, IR_TYPE[c.type]) for c in settings.parser().columns(lines) if c.name not in own
    ]
    return [*META_COLUMNS, *parsed, (LANDED_AT, "timestamp")]


def preview(settings: LogsSettings, rows: int) -> dict[str, Any]:
    """The files, the columns, and up to ``rows`` rows of the newest file."""
    glob = checked_glob(settings.glob)
    paths = matched(glob)
    cols = columns(settings)
    table = Table("preview", dict(cols), int(settings_registry.value("logs.max_line_bytes")))
    files, _gone = identify(paths, {})
    newest = sorted(files, key=lambda f: f.mtime, reverse=True)
    sample: list[dict[str, Any]] = []
    for found in newest:
        for batch in read_file(found, settings.parser(), table, rows):
            sample.extend(batch)
            break
        if sample:
            break
    return {
        "files": [
            {
                "path": path,
                "bytes": os.stat(path).st_size,
                "modified": datetime.fromtimestamp(os.stat(path).st_mtime, UTC).isoformat(),
            }
            for path in paths
        ],
        "columns": [{"name": name, "type": ir} for name, ir in cols],
        "rows": [
            {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
            for row in sample[:rows]
        ],
    }
