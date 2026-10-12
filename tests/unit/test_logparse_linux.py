# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the container and Linux log presets read the lines each project's documentation
gives (tests/unit/fixtures/logparse/linux), one fixture per preset; a CRI line the runtime split
into parts is one row."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "linux"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str) -> list[dict]:
    fmt = BUILT_IN[name]
    lines = (_FIXTURES / f"{name}.log").read_text().splitlines()
    return [row for line in lines if line.strip() for row in fmt.parse_many(line, _ctx())]


def test_the_linux_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in ("kubernetes_cri", "journald_json", "linux_auditd", "linux_dmesg"):
        assert names[name] == "linux"


def _cri_framed(data: bytes, start: int = 0, whole: bool = True):
    fmt = BUILT_IN["kubernetes_cri"]
    return list(fmt.frame("pod.log", io.BytesIO(data), start, whole))


def test_kubernetes_cri_joins_a_split_line_s_parts():
    data = (_FIXTURES / "kubernetes_cri.log").read_bytes()
    framed = _cri_framed(data)
    assert len(framed) == 3
    fmt = BUILT_IN["kubernetes_cri"]
    listening, split, done = (fmt.parse(text, _ctx()) for _, text, _ in framed)
    assert listening["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (listening["stream"], listening["parts"]) == ("stdout", 1)
    assert (split["stream"], split["parts"]) == ("stderr", 3)
    assert split["message"] == '{"level":"error","msg":"a long line the runtime split","code":500}'
    assert split["timestamp"] == datetime(2023, 5, 11, 8, 15, 24, tzinfo=_UTC)
    assert done["message"] == "done"
    # Each record's offset and end are its own: a read goes on from the one it reached.
    assert _cri_framed(data, framed[1][0]) == framed[1:]


def test_a_cri_line_whose_final_part_is_not_yet_written_is_left_for_the_next_read():
    data = b"2023-05-11T08:15:24Z stderr P begun, \n2023-05-11T08:15:24Z stderr P still "
    assert _cri_framed(data, whole=False) == []
    later = data + b"going \n2023-05-11T08:15:25Z stderr F and done\n"
    (record,) = _cri_framed(later, whole=False)
    assert BUILT_IN["kubernetes_cri"].parse(record[1], _ctx())["message"] == (
        "begun, still going and done"
    )


def test_journald_json_export():
    accepted, oom = rows("journald_json")
    assert accepted["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (accepted["syslog_identifier"], accepted["priority"], accepted["pid"]) == (
        "sshd",
        "6",
        "1234",
    )
    assert accepted["systemd_unit"] == "ssh.service"
    assert oom["transport"] == "kernel" and oom["pid"] is None
    assert accepted["__MONOTONIC_TIMESTAMP"] == "123456789"  # kept for the extra column


def test_auditd_records_of_one_event_share_its_serial():
    syscall, cwd, auth = rows("linux_auditd")
    assert syscall["timestamp"] == datetime(2013, 3, 28, 14, 36, 3, 243000, tzinfo=_UTC)
    assert (syscall["type"], syscall["serial"], cwd["serial"]) == ("SYSCALL", "24287", "24287")
    assert syscall["fields"]["comm"] == "cat" and syscall["fields"]["success"] == "no"
    assert syscall["fields"]["key"] == "sshd_config"
    assert cwd["fields"] == {"cwd": "/home/shadowman"}
    assert (auth["fields"]["op"], auth["fields"]["acct"], auth["fields"]["res"]) == (
        "PAM:authentication",
        "root",
        "failed",
    )


def test_dmesg_by_uptime_or_wall_clock():
    banner, usb, warning, link = rows("linux_dmesg")
    assert (banner["uptime_s"], banner["timestamp"]) == ("0.000000", None)
    assert usb["message"].startswith("usb 1-1: new high-speed USB device")
    assert (warning["facility"], warning["level"], warning["uptime_s"]) == (
        "kern",
        "warn",
        "13.000001",
    )
    assert link["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_LOCAL)
    assert link["uptime_s"] is None


@pytest.mark.parametrize("name", ["linux_auditd", "linux_dmesg"])
def test_a_line_in_another_form_is_refused(name):
    with pytest.raises(ParseError):
        BUILT_IN[name].parse("not a log line", _ctx())
