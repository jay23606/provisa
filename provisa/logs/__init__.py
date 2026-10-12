# Copyright (c) 2026 Kenneth Stott
# Canary: 94b72c2a-11a6-4579-80d9-910fea1807ef
#
# This source code is licensed under the Business Source License 1.1
"""Logs source (REQ-1996): the lines of log files matched by a glob, as the rows of one table.

Each row carries where it came from beside the columns its format gives: the file's identity
(``_file_id``, a checksum of its first bytes, so a renamed or compressed copy is the same file),
the name it was read under, the byte offset of the record's first line -- the two together are
the row's key, which dedupes a line read twice -- its raw text, why it could not be parsed when
it could not, and when it landed (the table's watermark for live delivery)."""

from __future__ import annotations

#: The source type's name, as a source row records it.
SOURCE_TYPE = "logs"
#: The schema the table picker lists a source's one table under: a log has none of its own.
SCHEMA = "default"

FILE_ID = "_file_id"
FILE_NAME = "_file_name"
LINE_OFFSET = "_line_offset"
#: Which of the record's entries the row is: 0 for a record of one row; a record that is a
#: batch of entries (CloudTrail's Records) gives a row per entry.
ENTRY = "_entry"
RAW = "_raw"
PARSE_ERROR = "_parse_error"
LANDED_AT = "_landed_at"

#: The columns that identify a row: the file it is in, where in it the record starts, and
#: which of the record's entries it is.
KEY: tuple[str, ...] = (FILE_ID, LINE_OFFSET, ENTRY)

#: The columns every Logs table has, before its format's, as (name, IR type).
META_COLUMNS: list[tuple[str, str]] = [
    (FILE_ID, "text"),
    (FILE_NAME, "text"),
    (LINE_OFFSET, "bigint"),
    (ENTRY, "bigint"),
    (RAW, "text"),
    (PARSE_ERROR, "text"),
]
