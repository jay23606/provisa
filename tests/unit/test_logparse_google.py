# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the Google log presets read the forms Google's documentation gives for each log
(tests/unit/fixtures/logparse/google), one fixture per preset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog, records

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "google"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str, fixture: str, *, keep_refused: bool = False) -> list:
    fmt = BUILT_IN[name]
    ctx = _ctx()
    body = [
        (i, line)
        for i, line in enumerate((_FIXTURES / fixture).read_text().splitlines())
        if line.strip()
    ]
    out: list = []
    for _, record in records(body, fmt.record_start):
        try:
            out.extend(fmt.parse_many(record, ctx))
        except ParseError as exc:
            if not keep_refused:
                raise
            out.append(str(exc))
    return out


def test_the_google_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in ("gcp_cloud_logging", "android_logcat", "chrome_net_export"):
        assert names[name] == "google"


def test_cloud_logging_entries_a_line_each_or_an_array():
    audit, stdout, request = rows("gcp_cloud_logging", "gcp_cloud_logging.json")
    assert audit["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (audit["severity"], audit["resource_type"]) == ("NOTICE", "gce_instance")
    assert audit["proto_payload"]["methodName"] == "v1.compute.instances.start"
    assert audit["text_payload"] is None
    assert stdout["text_payload"] == "Server listening on :8080"
    assert stdout["resource_labels"]["cluster_name"] == "c1"
    assert request["http_request"]["status"] == 200
    assert request["trace"].endswith("06796866738c859f2f19b7cfb3214824")


def test_logcat_threadtime_takes_its_year_from_the_file():
    found = rows("android_logcat", "android_logcat.log", keep_refused=True)
    assert isinstance(found[0], str)  # the buffer marker is not a message
    start, created, fatal = found[1:]
    assert start["timestamp"] == datetime(2026, 6, 27, 10, 41, 38, 528000, tzinfo=_LOCAL)
    assert (start["pid"], start["tid"], start["priority"], start["tag"]) == (
        "1234",
        "1250",
        "info",
        "ActivityManager",
    )
    assert created["message"] == "onCreate" and created["priority"] == "debug"
    assert (fatal["priority"], fatal["tag"]) == ("error", "AndroidRuntime")


def test_chrome_net_export_is_a_row_per_event_named_by_its_constants():
    alive, start_job, end = rows("chrome_net_export", "chrome_net_export.json")
    origin = datetime(2023, 5, 11, 8, 15, 23, tzinfo=_UTC)
    assert alive["time"] == origin + timedelta(milliseconds=5000)
    assert (alive["event_type"], alive["phase"], alive["source_type"]) == (
        "REQUEST_ALIVE",
        "PHASE_BEGIN",
        "URL_REQUEST",
    )
    assert start_job["params"]["url"] == "https://www.example.com/"
    assert (end["phase"], end["source_id"]) == ("PHASE_END", 14)


def test_a_net_export_event_its_constants_do_not_name_is_refused():
    doc = (_FIXTURES / "chrome_net_export.json").read_text().replace('"type": 104', '"type": 999')
    with pytest.raises(ParseError, match="999"):
        BUILT_IN["chrome_net_export"].parse_many(doc, _ctx())
