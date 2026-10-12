# Copyright (c) 2026 Kenneth Stott
# Canary: 263c2cda-1e30-4e72-abb9-5e61d6f8b34c
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the Microsoft log presets read the lines Microsoft's own documentation gives for each
log (tests/unit/fixtures/logparse/microsoft), one fixture per preset. Windows writes its own logs in
the server's local time, read in the zone of the file's last write."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog, records

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "microsoft"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str, fixture: str | None = None, *, keep_refused: bool = False) -> list:
    """A fixture read as the Logs source reads a file: header lines to the format, the rest framed
    into records, each record's rows -- or, with ``keep_refused``, the refusal's text in its place."""
    fmt = BUILT_IN[name]
    ctx = _ctx()
    lines = (_FIXTURES / (fixture or f"{name}.log")).read_text().splitlines()
    body: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if fmt.header_prefix and line.startswith(fmt.header_prefix):
            fmt.on_header(line, ctx)
        elif line.strip():
            body.append((i, line))
    out: list = []
    for _, record in records(body, fmt.record_start):
        try:
            out.extend(fmt.parse_many(record, ctx))
        except ParseError as exc:
            if not keep_refused:
                raise
            out.append(str(exc))
    return out


def test_the_microsoft_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in (
        "ms_iis",
        "ms_windows_firewall",
        "ms_dns_debug",
        "ms_dhcp_audit",
        "ms_exchange_tracking",
        "ms_sqlserver_errorlog",
        "azure_storage_analytics",
        "azure_monitor",
    ):
        assert names[name] == "microsoft"


def test_iis_log_by_its_header():
    get, post = rows("ms_iis")
    assert get["timestamp"] == datetime(2023, 5, 11, 8, 0, 1, tzinfo=_UTC)
    assert (get["cs_method"], get["cs_uri_stem"], get["sc_status"]) == (
        "GET",
        "/default.htm",
        "200",
    )
    assert get["cs_uri_query"] is None and get["cs_username"] is None
    assert get["cs_user_agent"] == "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)"
    assert (post["cs_username"], post["sc_status"], post["time_taken"]) == (
        "CONTOSO\\bob",
        "401",
        "4",
    )


def test_windows_firewall_log_in_local_time():
    allowed, dropped = rows("ms_windows_firewall")
    assert allowed["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_LOCAL)
    assert (allowed["action"], allowed["protocol"], allowed["dst_port"]) == ("ALLOW", "TCP", "443")
    assert allowed["path"] == "SEND" and allowed["tcpflags"] is None
    assert (dropped["action"], dropped["src_ip"], dropped["size"]) == ("DROP", "10.0.0.5", "78")


def test_dns_debug_log():
    found = rows("ms_dns_debug", keep_refused=True)
    # The file's opening notes are not packets: kept, refused.
    assert all(isinstance(r, str) for r in found[:2])
    query, response = found[2], found[3]
    assert query["timestamp"] == datetime(2017, 4, 25, 11, 13, 27, tzinfo=_LOCAL)
    assert (query["direction"], query["remote_ip"], query["xid"]) == ("receive", "10.0.0.5", "e36d")
    assert (query["response"], query["opcode"], query["flags"], query["rcode"]) == (
        False,
        "Q",
        "D",
        "NOERROR",
    )
    assert (query["question_type"], query["question_name"]) == ("A", "www.example.com")
    assert (response["response"], response["direction"], response["flags"]) == (True, "send", "DR")


def test_dhcp_audit_log_events_after_its_preamble():
    found = rows("ms_dhcp_audit", keep_refused=True)
    events = [r for r in found if isinstance(r, dict)]
    assert len(events) == 2
    assert all("not an event" in r for r in found if isinstance(r, str))
    started, assigned = events
    assert (started["event_id"], started["description"]) == ("00", "Started")
    assert assigned["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_LOCAL)
    assert (assigned["ip_address"], assigned["host_name"], assigned["mac_address"]) == (
        "192.168.1.50",
        "laptop1.contoso.com",
        "AABBCCDDEEFF",
    )
    assert assigned["vendor_class_ascii"] == "MSFT 5.0" and assigned["user_name"] is None


def test_exchange_message_tracking_log():
    (row,) = rows("ms_exchange_tracking")
    assert row["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456000, tzinfo=_UTC)
    assert (row["event_id"], row["source"]) == ("RECEIVE", "STOREDRIVER")
    assert row["message_subject"] == "Quarterly report, Q2"
    assert (row["sender_address"], row["recipient_address"]) == (
        "alice@contoso.com",
        "bob@contoso.com",
    )
    assert row["server_ip"] is None


def test_sql_server_errorlog_joins_continuation_lines():
    startup, master, error, login = rows("ms_sqlserver_errorlog")
    assert startup["timestamp"] == datetime(2023, 3, 15, 10, 1, 22, 340000, tzinfo=_LOCAL)
    assert startup["source"] == "Server"
    assert startup["message"].splitlines()[-1].strip() == "Copyright (C) 2019 Microsoft Corporation"
    assert (master["source"], master["message"]) == ("spid9s", "Starting up database 'master'.")
    assert error["message"].startswith("Error: 18456")
    assert login["message"].endswith("[CLIENT: 10.0.0.9]")


def test_azure_storage_analytics_log():
    (row,) = rows("azure_storage_analytics")
    assert row["request_start_time"] == datetime(2014, 6, 19, 22, 59, 23, 196776, tzinfo=_UTC)
    assert (row["operation_type"], row["request_status"], row["http_status_code"]) == (
        "GetBlob",
        "Success",
        "200",
    )
    assert (
        row["request_url"]
        == "https://account1.blob.core.windows.net/thumbnails/lake.jpg?timeout=30000"
    )
    assert row["last_modified_time"] == "Thursday, 09-Jan-14 00:00:00 GMT"
    assert row["request_md5"] is None
    assert row["user_object_id"] is None  # a version 1.0 line has no 2.0 fields


def test_azure_monitor_record_and_activity_log_export():
    vault, started, failed = rows("azure_monitor", "azure_monitor.json")
    assert vault["time"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (vault["category"], vault["operation_name"]) == ("AuditEvent", "VaultGet")
    assert vault["properties"]["httpStatusCode"] == 200
    assert (started["result_type"], failed["result_type"]) == ("Success", "Failure")
    assert failed["caller_ip_address"] is None


@pytest.mark.parametrize(
    "name", ["ms_dns_debug", "ms_sqlserver_errorlog", "azure_storage_analytics"]
)
def test_a_line_in_another_form_is_refused(name):
    with pytest.raises(ParseError):
        BUILT_IN[name].parse("not a log line", _ctx())
