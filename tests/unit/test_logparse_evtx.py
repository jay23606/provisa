# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: Windows Event Log files (.evtx) are read record by record, each record's XML a row.

The fixture, tests/unit/fixtures/logparse/microsoft/windows_system.evtx, is the first 69,632 bytes
of python-evtx's own test data tests/data/system.evtx (Apache License 2.0), itself from plaso's
test data (Apache License 2.0): its header and first chunk, 153 records of a test lab machine's
System log. Its source and licence are noted in that folder's README.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from provisa.logparse import BUILT_IN, FileContext, catalog

_EVTX = Path(__file__).parent / "fixtures" / "logparse" / "microsoft" / "windows_system.evtx"


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc))


def _framed(start: int = 0) -> list[tuple[int, str, int]]:
    fmt = BUILT_IN["windows_evtx"]
    with _EVTX.open("rb") as stream:
        return list(fmt.frame(str(_EVTX), stream, start, True))


def test_windows_event_log_is_offered_with_the_microsoft_presets():
    assert {e["name"]: e["group"] for e in catalog()}["windows_evtx"] == "microsoft"
    assert BUILT_IN["windows_evtx"].frames_bytes is True


def test_each_record_is_a_row_of_its_system_fields():
    framed = _framed()
    assert len(framed) == 153
    offset, text, end = framed[0]
    assert (offset, end) == (4608, framed[1][0])
    row = BUILT_IN["windows_evtx"].parse(text, _ctx())
    assert row["time_created"] == datetime(2012, 3, 14, 4, 17, 43, 354563, tzinfo=timezone.utc)
    assert (row["event_id"], row["event_record_id"], row["channel"]) == ("105", "12049", "System")
    assert row["provider"] == "Microsoft-Windows-Eventlog"
    assert (row["process_id"], row["thread_id"]) == ("820", "2868")
    assert row["user_data"]["AutoBackup"]["Channel"] == "System"
    assert row["event_data"] is None
    ids = {BUILT_IN["windows_evtx"].parse(t, _ctx())["event_id"] for _, t, _ in framed}
    assert {"1", "12", "13", "18", "105", "1014", "1074", "20010", "50037"} <= ids


def test_a_read_goes_on_from_the_record_it_reached():
    framed = _framed()
    resumed = _framed(framed[10][0])
    assert resumed == framed[10:]
    assert framed[-1][2] == 69424
