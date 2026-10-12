# Copyright (c) 2026 Kenneth Stott
# Canary: 0c588a15-512e-4532-9d92-9c67880e22c2
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the shared log-parser library's core formats, record framing and header-declared
columns. The syslog and install-log lines are macOS lines with the host renamed; the others are
the forms each format's own documentation gives."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog, format_for, records
from provisa.logparse.coltypes import coerce, infer_type

_EDT = timezone(timedelta(hours=-4))
_CTX = FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_EDT))


def _cols(fmt, preview):
    return {c.name: c.type for c in fmt.columns(preview)}


# --- syslog -------------------------------------------------------------------------------


def test_bsd_syslog_takes_its_year_from_the_file():
    row = BUILT_IN["rfc3164"].parse(
        "Oct 12 00:09:29 host-a syslogd[603]: ASL Sender Statistics", _CTX
    )
    assert row == {
        "timestamp": datetime(2026, 10, 12, 0, 9, 29, tzinfo=_EDT),
        "facility": None,
        "severity": None,
        "host": "host-a",
        "process": "syslogd",
        "pid": 603,
        "message": "ASL Sender Statistics",
    }


def test_a_bsd_line_from_a_month_after_the_file_s_last_write_is_from_the_year_before():
    row = BUILT_IN["rfc3164"].parse("<34>Dec 31 23:59:59 mymachine su: 'su root' failed", _CTX)
    assert row["timestamp"].year == 2025
    assert (row["facility"], row["severity"], row["pid"]) == (4, 2, None)


def test_rfc5424_keeps_its_structured_data_as_json():
    # RFC 5424 section 6.5, example 3.
    line = (
        "<165>1 2003-10-11T22:14:15.003Z mymachine.example.com evntslog - ID47 "
        '[exampleSDID@32473 iut="3" eventSource="Application" eventID="1011"] '
        "﻿An application event log entry..."
    )
    row = BUILT_IN["rfc5424"].parse(line, _CTX)
    assert row["timestamp"] == datetime(2003, 10, 11, 22, 14, 15, 3000, tzinfo=timezone.utc)
    assert (row["facility"], row["severity"], row["version"]) == (20, 5, 1)
    assert row["procid"] is None and row["msgid"] == "ID47"
    assert row["structured_data"] == {
        "exampleSDID@32473": {"iut": "3", "eventSource": "Application", "eventID": "1011"}
    }
    assert row["message"] == "An application event log entry..."


def test_rfc5424_with_no_structured_data_or_message():
    row = BUILT_IN["rfc5424"].parse(
        "<34>1 2003-10-11T22:14:15.003Z mymachine.example.com su - ID47 -", _CTX
    )
    assert row["structured_data"] is None and row["message"] is None


def test_the_macos_install_log_reads_its_hours_only_offset():
    line = "2026-08-30 14:18:15-04 host-b softwareupdated[36904]: Package Authoring: error running"
    row = BUILT_IN["macos_install"].parse(line, _CTX)
    assert row["timestamp"] == datetime(2026, 8, 30, 14, 18, 15, tzinfo=_EDT)
    assert (row["process"], row["pid"]) == ("softwareupdated", 36904)
    spaced = "2026-10-11 19:51:31-04 host-b Software Update[55042]: Launched with args: {"
    row = BUILT_IN["macos_install"].parse(spaced, _CTX)
    assert (row["process"], row["pid"], row["message"]) == (
        "Software Update",
        55042,
        "Launched with args: {",
    )
    # What the system writes there while it starts is in the BSD form.
    booted = BUILT_IN["macos_install"].parse(
        "Oct 11 20:03:24 localhost opendirectoryd[69]: up", _CTX
    )
    assert booted["timestamp"] == datetime(2026, 10, 11, 20, 3, 24, tzinfo=_EDT)
    assert BUILT_IN["macos_install"].record_start.match("Oct 11 20:03:24 localhost x[1]: y")


def test_an_indented_line_continues_the_syslog_record_above_it():
    fmt = BUILT_IN["rfc3164"]
    lines = [
        (0, "Oct 12 00:05:00 host-a syslogd[603]: Configuration Notice:"),
        (60, '\tASL Module "com.apple.cdscheduler" claims selected messages.'),
        (120, "Oct 12 00:05:01 host-a syslogd[603]: ASL Sender Statistics"),
    ]
    (first, at), (second, _) = [(text, offset) for offset, text in records(lines, fmt.record_start)]
    assert at == 0
    assert fmt.parse(first, _CTX)["message"] == (
        'Configuration Notice:\n\tASL Module "com.apple.cdscheduler" claims selected messages.'
    )
    install = BUILT_IN["macos_install"]
    framed = list(
        records(
            [
                (0, "2026-08-30 14:18:15-04 host-b installer[1]: Packages:"),
                (55, "\t140-17812\t | Tools"),
            ],
            install.record_start,
        )
    )
    assert install.parse(framed[0][1], _CTX)["message"] == "Packages:\n\t140-17812\t | Tools"


def test_a_line_not_in_the_form_is_refused_by_the_format_s_label():
    with pytest.raises(ParseError, match="BSD syslog"):
        BUILT_IN["rfc3164"].parse("garbage", _CTX)


# --- web access logs ---------------------------------------------------------------------------


def test_common_and_combined_log_format():
    # The Apache HTTP Server log-file documentation's examples.
    clf = '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326'
    row = BUILT_IN["clf"].parse(clf, _CTX)
    assert row["timestamp"] == datetime(
        2000, 10, 10, 13, 55, 36, tzinfo=timezone(timedelta(hours=-7))
    )
    assert (row["ident"], row["user"], row["method"], row["path"], row["protocol"]) == (
        None,
        "frank",
        "GET",
        "/apache_pb.gif",
        "HTTP/1.0",
    )
    assert (row["status"], row["bytes"]) == (200, 2326)
    combined = clf + ' "http://www.example.com/start.html" "Mozilla/4.08 [en] (Win98; I ;Nav)"'
    row = BUILT_IN["combined"].parse(combined, _CTX)
    assert row["referer"] == "http://www.example.com/start.html"
    assert row["user_agent"] == "Mozilla/4.08 [en] (Win98; I ;Nav)"
    with pytest.raises(ParseError):
        BUILT_IN["clf"].parse(combined, _CTX)


# --- self-describing records ------------------------------------------------------------------


def test_json_lines_types_its_columns_from_the_preview():
    preview = [
        '{"ts": "2026-10-12T12:00:00Z", "level": "info", "n": 1, "ok": true, "ctx": {"a": 1}}',
        '{"ts": "2026-10-12T12:00:01Z", "level": "warn", "n": 2.5, "ok": false}',
        "not json",
    ]
    assert _cols(BUILT_IN["jsonl"], preview) == {
        "ts": "timestamp",
        "level": "string",
        "n": "float",
        "ok": "boolean",
        "ctx": "json",
        "extra": "json",
    }
    with pytest.raises(ParseError, match="not JSON"):
        BUILT_IN["jsonl"].parse("not json", _CTX)
    with pytest.raises(ParseError, match="not an object"):
        BUILT_IN["jsonl"].parse("[1, 2]", _CTX)


def test_logfmt_reads_quoted_values_and_bare_keys():
    # The logfmt form as Brandur Leach's description of it gives it.
    line = 'at=info method=GET path=/ host=mutelight.org fwd="124.133.52.161" status=200 bytes=1234 dry'
    row = BUILT_IN["logfmt"].parse(line, _CTX)
    assert row == {
        "at": "info",
        "method": "GET",
        "path": "/",
        "host": "mutelight.org",
        "fwd": "124.133.52.161",
        "status": "200",
        "bytes": "1234",
        "dry": True,
    }
    assert _cols(BUILT_IN["logfmt"], [line])["status"] == "integer"
    assert BUILT_IN["logfmt"].parse('msg="a \\"quoted\\" word"', _CTX) == {"msg": 'a "quoted" word'}


# --- header-declared columns ---------------------------------------------------------------------

_IIS = [
    "#Software: Microsoft Internet Information Services 10.0",
    "#Version: 1.0",
    "#Date: 2026-10-12 12:00:00",
    "#Fields: date time s-ip cs-method cs-uri-stem cs-uri-query s-port cs-username c-ip "
    "cs(User-Agent) sc-status sc-substatus sc-win32-status time-taken",
    "2026-10-12 12:00:01 10.0.0.1 GET /default.htm - 80 - 192.0.2.7 Mozilla/5.0 200 0 0 15",
]


def test_w3c_columns_come_from_the_fields_header():
    fmt = BUILT_IN["w3c"]
    cols = _cols(fmt, _IIS)
    assert list(cols)[:4] == ["timestamp", "s_ip", "cs_method", "cs_uri_stem"]
    assert cols["cs_user_agent"] == "string" and cols["sc_status"] == "integer"
    assert cols["extra"] == "json"
    ctx = FileContext(mtime=_CTX.mtime)
    for line in _IIS[:4]:
        fmt.on_header(line, ctx)
    assert ctx.directives["Software"] == "Microsoft Internet Information Services 10.0"
    row = fmt.parse(_IIS[4], ctx)
    assert row["timestamp"] == datetime(2026, 10, 12, 12, 0, 1, tzinfo=timezone.utc)
    assert row["cs_uri_query"] is None and row["sc_status"] == "200"


def test_a_w3c_line_before_any_header_or_short_of_its_fields_is_refused():
    fmt = BUILT_IN["w3c"]
    with pytest.raises(ParseError, match="no #Fields"):
        fmt.parse(_IIS[4], FileContext(mtime=_CTX.mtime))
    ctx = FileContext(mtime=_CTX.mtime, fields=["date", "time", "c-ip"])
    with pytest.raises(ParseError, match="2 values for the header's 3"):
        fmt.parse("2026-10-12 12:00:01", ctx)


# --- CEF, GELF ------------------------------------------------------------------------------


def test_cef_header_and_extension():
    # The ArcSight CEF implementation standard's example, after a syslog header.
    line = (
        "Sep 19 08:26:10 host CEF:0|Security|threatmanager|1.0|100|worm successfully stopped|10|"
        "src=10.0.0.1 dst=2.1.2.2 spt=1232 msg=Detected a threat. No action needed"
    )
    row = BUILT_IN["cef"].parse(line, _CTX)
    assert (row["device_vendor"], row["signature_id"], row["severity"]) == ("Security", "100", "10")
    assert row["extension"] == {
        "src": "10.0.0.1",
        "dst": "2.1.2.2",
        "spt": "1232",
        "msg": "Detected a threat. No action needed",
    }
    escaped = "CEF:0|a\\|b|p|1|1|n|3|k=x\\=y"
    row = BUILT_IN["cef"].parse(escaped, _CTX)
    assert row["device_vendor"] == "a|b" and row["extension"] == {"k": "x=y"}


def test_gelf_keeps_its_underscore_fields_as_additional():
    # The GELF payload specification's example.
    line = (
        '{"version": "1.1", "host": "example.org", "short_message": "A short message", '
        '"full_message": "Backtrace here\\n\\nmore stuff", "timestamp": 1385053862.3072, '
        '"level": 1, "_user_id": 9001, "_some_info": "foo"}'
    )
    row = BUILT_IN["gelf"].parse(line, _CTX)
    assert row["timestamp"] == datetime.fromtimestamp(1385053862.3072, tz=timezone.utc)
    assert row["additional"] == {"user_id": 9001, "some_info": "foo"}
    with pytest.raises(ParseError, match="host and short_message"):
        BUILT_IN["gelf"].parse('{"version": "1.1"}', _CTX)


# --- regex and multi-line records ------------------------------------------------------------


def test_a_regex_format_s_named_groups_are_its_columns():
    fmt = format_for("regex", r"(?P<level>[A-Z]+) (?P<message>.*)")
    assert _cols(fmt, []) == {"level": "string", "message": "string"}
    assert fmt.parse("WARN disk low", _CTX) == {"level": "WARN", "message": "disk low"}
    with pytest.raises(ValueError, match="names no group"):
        format_for("regex", r"[A-Z]+ .*")
    with pytest.raises(ValueError, match="not a regular expression"):
        format_for("regex", r"(?P<a>")
    with pytest.raises(ValueError, match="needs a pattern"):
        format_for("regex")


def test_a_record_start_joins_a_stack_trace_into_its_record():
    lines = [
        (0, "stray continuation"),
        (19, "2026-10-12 12:00:00 ERROR boom"),
        (50, "Traceback (most recent call last):"),
        (85, '  File "x.py", line 1'),
        (107, "2026-10-12 12:00:01 INFO fine"),
    ]
    start = re.compile(r"\d{4}-\d{2}-\d{2} ")
    assert list(records(lines, start)) == [
        (0, "stray continuation"),
        (
            19,
            '2026-10-12 12:00:00 ERROR boom\nTraceback (most recent call last):\n  File "x.py", line 1',
        ),
        (107, "2026-10-12 12:00:01 INFO fine"),
    ]
    assert list(records(lines, None)) == lines
    fmt = format_for("regex", r"(?P<when>\S+ \S+) (?P<level>\w+) (?P<message>.*)", r"\d{4}-")
    assert fmt.parse(list(records(lines, fmt.record_start))[1][1], _CTX)["message"].endswith(
        "line 1"
    )


# --- the registry and column typing --------------------------------------------------------------


def test_the_catalog_names_every_format_and_a_built_in_takes_no_pattern():
    names = [f["name"] for f in catalog()]
    assert names == [*BUILT_IN, "regex"]
    assert all(f["label"] and f["group"] for f in catalog())
    with pytest.raises(ValueError, match="takes no pattern"):
        format_for("jsonl", r"(?P<a>.)")
    with pytest.raises(ValueError, match="no log format named 'nope'"):
        format_for("nope")


def test_infer_type_and_coerce():
    assert infer_type(["1", "2", None]) == "integer"
    assert infer_type(["1", "2.5"]) == "float"
    assert infer_type(["true", "False"]) == "boolean"
    assert infer_type(["2026-10-12 12:59:01.123456-0400"]) == "timestamp"
    assert infer_type(["1", "x"]) == "string"
    assert infer_type([]) == "string"
    assert coerce("7", "integer") == 7 and coerce("", "integer") is None
    with pytest.raises(ValueError):
        coerce("x", "integer")
    with pytest.raises(ValueError):
        coerce(True, "integer")
