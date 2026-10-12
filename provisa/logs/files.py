# Copyright (c) 2026 Kenneth Stott
# Canary: 29395723-0542-4057-b99e-8bda445f1425
#
# This source code is licensed under the Business Source License 1.1
"""The files of a Logs source and what of each has been read (REQ-1996).

IDENTITY. A file is known by a checksum of its first bytes (up to :data:`HEAD`, decompressed),
not by its name: when ``system.log`` is rotated to ``system.log.0`` and compressed to
``system.log.0.gz`` -- a new inode -- the copy's first bytes are still the file's, and it is the
same file, read on from where the last read reached. A file shorter than :data:`HEAD` is known by
the bytes it has, and those must stay its first as it grows; such a short head names the file
only together with its inode, or in a compressed copy (the rotation of a file that was short),
so two short files that start alike are not taken for one. Several files the glob matches that
are one file (a rotated copy beside its compressed one) are read once.

WHERE A READ REACHED. Per file: the byte offset, in its decompressed text, past the last record
read; the columns its header declared (W3C). A file found shorter than that offset was
truncated: it is a new file, read from its start, and the rows of the one it was stay.

WHAT A READ LEAVES. A file that may still grow (one not compressed) is read to its last whole
line; and, for a format whose records span lines, to the start of its last record, which the
next line may yet continue -- unless the file has not been written for :data:`QUIET_SECONDS`:
a writer puts a record and the lines that continue it down together, so a record a quiet file
ends with is whole, and a live table is not a record behind."""

from __future__ import annotations

import bz2
import glob as globbing
import gzip
import hashlib
import io
import json
import os
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, BinaryIO

from provisa.logparse import FileContext, Format, ParseError, records
from provisa.logparse.coltypes import coerce
from provisa.logs import FILE_ID, FILE_NAME, LINE_OFFSET, PARSE_ERROR, RAW
from provisa.logs.roots import checked_file

#: How many of a file's first bytes identify it.
HEAD = 4096
#: How long a file goes unwritten before the record it ends with is taken as whole.
QUIET_SECONDS = 2.0

_GZIP = b"\x1f\x8b"
_BZIP2 = b"BZh"

#: A Logs column's IR type as the parser library names it.
_LOG_TYPE = {
    "text": "string",
    "bigint": "integer",
    "integer": "integer",
    "double": "float",
    "float": "float",
    "boolean": "boolean",
    "timestamp": "timestamp",
    "json": "json",
}
IR_TYPE = {
    "string": "text",
    "integer": "bigint",
    "float": "double",
    "boolean": "boolean",
    "timestamp": "timestamp",
    "json": "json",
}


def log_type(ir_type: str) -> Any:
    if ir_type not in _LOG_TYPE:
        raise ValueError(f"a Logs column cannot be of type {ir_type!r}")
    return _LOG_TYPE[ir_type]


def compression(path: str) -> str | None:
    """``gzip`` or ``bzip2`` by the file's first bytes (never its name), or None."""
    with open(path, "rb") as f:
        magic = f.read(3)
    if magic.startswith(_GZIP):
        return "gzip"
    if magic == _BZIP2:
        return "bzip2"
    return None


def opened(path: str, kind: str | None) -> BinaryIO:
    if kind == "gzip":
        return gzip.open(path, "rb")  # type: ignore[return-value]
    if kind == "bzip2":
        return bz2.open(path, "rb")  # type: ignore[return-value]
    return open(path, "rb")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FileState:
    """What of one file has been read, as it is kept between reads."""

    id: str
    head_len: int
    head: str
    inode: int
    offset: int = 0
    fields: list[str] | None = None
    directives: dict[str, str] = field(default_factory=dict)

    def token(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def of(cls, token: str) -> FileState:
        return cls(**json.loads(token))


@dataclass
class Found:
    """A file the glob matched: where it is, how it is compressed, and what was kept of it."""

    path: str
    kind: str | None
    mtime: datetime
    size: int
    state: FileState
    #: Not written for :data:`QUIET_SECONDS` when it was found.
    quiet: bool = False

    @property
    def complete(self) -> bool:
        """A compressed file is not written to again; any other may still grow."""
        return self.kind is not None


def matched(glob: str) -> list[str]:
    """The regular files ``glob`` matches, in name order, each inside an allowed root once its
    symlinks are followed (refused by name otherwise)."""
    paths = sorted(p for p in globbing.glob(glob) if os.path.isfile(p))
    for path in paths:
        checked_file(path)
    return paths


def _head(path: str, kind: str | None) -> bytes:
    with opened(path, kind) as f:
        return f.read(HEAD)


def identify(paths: list[str], kept: dict[str, FileState]) -> tuple[list[Found], list[str]]:
    """The files of ``paths`` as the files they are, each with what was kept of it -- a new
    file with nothing -- and the ids of the kept files none of them is now. An empty file is
    not yet a file: it has no first bytes to be known by."""
    found: dict[str, Found] = {}
    for path in paths:
        stat = os.stat(path)
        kind = compression(path)
        head = _head(path, kind)
        if not head:
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC).astimezone()

        def same(state: FileState) -> bool:
            if len(head) < state.head_len or _digest(head[: state.head_len]) != state.head:
                return False
            return state.head_len >= HEAD or state.inode == stat.st_ino or kind is not None

        known = [s for s in [*kept.values(), *(f.state for f in found.values())] if same(s)]
        # A file's own inode is the better match where its head is matched more than once.
        state = next((s for s in known if s.inode == stat.st_ino), known[0] if known else None)
        if state is None:
            state = FileState(_digest(head)[:32], len(head), _digest(head), stat.st_ino)
        elif state.id in found:
            here = found[state.id]
            if here.complete or kind is None:
                # The same file again, read once: from its compressed copy where there is one,
                # whose last line is whole.
                continue
        else:
            state = FileState(**asdict(state))
        if kind is None and state.inode == stat.st_ino and stat.st_size < state.offset:
            # Truncated: a new file in the old one's place.
            state = FileState(
                _digest(f"{state.id}:{stat.st_mtime_ns}".encode())[:32],
                len(head),
                _digest(head),
                stat.st_ino,
            )
        if len(head) > state.head_len:
            state.head_len, state.head = len(head), _digest(head)
        state.inode = stat.st_ino
        quiet = time.time() - stat.st_mtime >= QUIET_SECONDS
        found[state.id] = Found(path, kind, mtime, stat.st_size, state, quiet)
    gone = sorted(set(kept) - set(found))
    return list(found.values()), gone


def _lines(f: BinaryIO, start: int, whole: bool) -> Iterator[tuple[int, str, int]]:
    """``(offset, line, end)`` from ``start``: the line without its ending, and the offset after
    it. A last line with no ending is given only when ``whole``."""
    offset = start
    for raw in f:
        end = offset + len(raw)
        if not raw.endswith(b"\n"):
            if whole:
                yield offset, raw.decode("utf-8", "replace"), end
            return
        yield offset, raw.rstrip(b"\r\n").decode("utf-8", "replace"), end
        offset = end


def _seek(f: BinaryIO, kind: str | None, offset: int) -> None:
    if kind is None:
        f.seek(offset)
        return
    left = offset
    while left:
        skipped = len(f.read(min(left, 1 << 20)))
        if not skipped:
            return
        left -= skipped


@dataclass
class Table:
    """The table a file's records become rows of: its columns by name, as IR types."""

    name: str
    columns: dict[str, str]
    max_line_bytes: int


def _value(value: Any, ir_type: str) -> Any:
    kind = log_type(ir_type)
    coerced = coerce(value, kind)
    if isinstance(coerced, datetime) and coerced.tzinfo is not None:
        coerced = coerced.astimezone(UTC).replace(tzinfo=None)
    return coerced


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def row_of(
    text: str, offset: int, found: Found, fmt: Format, ctx: FileContext, table: Table
) -> dict[str, Any]:
    """One record as a row of ``table``: what its format reads of it, typed as the table's
    columns are; a field the table has no column for is kept in its ``extra`` column, where it
    has one. A record its format cannot read, or a value its column cannot hold, says why in
    the parse-error column; its raw text is always there."""
    row: dict[str, Any] = {
        FILE_ID: found.state.id,
        FILE_NAME: found.path,
        LINE_OFFSET: offset,
        RAW: text,
        PARSE_ERROR: None,
    }
    size = len(text.encode("utf-8"))
    if size > table.max_line_bytes:
        row[RAW] = text.encode("utf-8")[: table.max_line_bytes].decode("utf-8", "ignore")
        row[PARSE_ERROR] = (
            f"{size} bytes, longer than the {table.max_line_bytes} a record may be; its first are kept"
        )
        return row
    try:
        parsed = fmt.parse(text, ctx)
    except ParseError as exc:
        row[PARSE_ERROR] = str(exc)
        return row
    errors: list[str] = []
    extra: dict[str, Any] = {}
    for name, value in parsed.items():
        if name in row:
            continue  # a field named as the row's own: its raw text still holds it
        if name in table.columns and name != "extra":
            try:
                row[name] = _value(value, table.columns[name])
            except (ValueError, TypeError) as exc:
                row[name] = None
                errors.append(f"{name}: {exc}")
        elif value is not None:
            extra[name] = _jsonable(value)
    if "extra" in table.columns:
        row["extra"] = extra or None
    row[PARSE_ERROR] = "; ".join(errors) or None
    return row


def read_file(
    found: Found, fmt: Format, table: Table, batch: int
) -> Iterator[list[dict[str, Any]]]:
    """The rows of ``found`` past where its last read reached, ``batch`` at a time; ``found``'s
    state moves past each batch's records as it is given."""
    state = found.state
    ctx = FileContext(mtime=found.mtime, fields=state.fields, directives=dict(state.directives))
    whole = found.complete
    held_end: dict[int, int] = {}  # a line's offset -> the offset after it

    def lines() -> Iterator[tuple[int, str]]:
        with opened(found.path, found.kind) as f:
            _seek(f, found.kind, state.offset)
            for offset, line, end in _lines(f, state.offset, whole):
                held_end[offset] = end
                yield offset, line

    rows: list[dict[str, Any]] = []
    pending: tuple[int, str] | None = None

    def take(record: tuple[int, str]) -> None:
        offset, text = record
        # The offset past the record: past each of its lines in turn.
        end = offset
        for _ in range(text.count("\n") + 1):
            end = held_end.pop(end)
        if fmt.header_prefix is not None and text.startswith(fmt.header_prefix):
            fmt.on_header(text, ctx)
        else:
            rows.append(row_of(text, offset, found, fmt, ctx, table))
        state.offset = end
        state.fields, state.directives = ctx.fields, dict(ctx.directives)

    # A format whose records span lines holds each record until the next one starts: only
    # then is it known to be whole.
    spanning = fmt.record_start is not None and fmt.header_prefix is None
    for record in records(lines(), fmt.record_start if spanning else None):
        if spanning:
            if pending is not None:
                take(pending)
            pending = record
        else:
            take(record)
        if len(rows) >= batch:
            yield rows
            rows = []
    if pending is not None and (whole or found.quiet):
        take(pending)  # a file not written to again, or not lately: its last record is whole
    if rows:
        yield rows


def preview(glob: str, lines: int) -> list[str]:
    """The first ``lines`` lines of the files ``glob`` matches, newest file first: what a
    format's columns are worked out from."""
    out: list[str] = []
    paths = sorted(matched(glob), key=lambda p: os.stat(p).st_mtime, reverse=True)
    for path in paths:
        with opened(path, compression(path)) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            for line in text:
                out.append(line.rstrip("\r\n"))
                if len(out) >= lines:
                    return out
    return out
