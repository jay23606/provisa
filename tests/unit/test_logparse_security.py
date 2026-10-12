# Copyright (c) 2026 Kenneth Stott
# Canary: 3724306a-2e6e-444d-8e69-f4da417579a2
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the network security monitor log presets read the forms each project's documentation
gives (tests/unit/fixtures/logparse/security), one fixture per preset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "security"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str) -> tuple[list[dict], FileContext]:
    fmt = BUILT_IN[name]
    ctx = _ctx()
    out: list[dict] = []
    for line in (_FIXTURES / f"{name}.log").read_text().splitlines():
        if fmt.header_prefix and line.startswith(fmt.header_prefix):
            fmt.on_header(line, ctx)
        elif line.strip():
            out.extend(fmt.parse_many(line, ctx))
    return out, ctx


def test_the_security_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in ("zeek_tsv", "zeek_json", "suricata_eve", "snort_fast"):
        assert names[name] == "security"


def test_zeek_tab_separated_log_by_its_header():
    (http, dns), ctx = rows("zeek_tsv")
    assert ctx.directives["path"] == "conn"
    assert http["ts"] == datetime(2019, 4, 17, 15, 48, 56, 237234, tzinfo=_UTC)
    assert (http["uid"], http["id_orig_h"], http["id_resp_p"]) == (
        "CPRxOZ4hSy8ZJ1Ehc5",
        "192.168.4.76",
        "80",
    )
    assert (http["local_orig"], http["tunnel_parents"]) == (None, [])
    assert (dns["local_orig"], dns["service"]) == (True, "dns")
    preview = (_FIXTURES / "zeek_tsv.log").read_text().splitlines()
    cols = {c.name: c.type for c in BUILT_IN["zeek_tsv"].columns(preview)}
    assert (cols["ts"], cols["id_orig_p"], cols["duration"], cols["local_orig"]) == (
        "timestamp",
        "integer",
        "float",
        "boolean",
    )
    assert cols["tunnel_parents"] == "json"


def test_zeek_json_log_with_either_time_form():
    (epoch_ts, iso_ts), _ = rows("zeek_json")
    assert epoch_ts["ts"] == datetime(2019, 4, 17, 15, 48, 56, 237234, tzinfo=_UTC)
    assert iso_ts["ts"] == datetime(2019, 4, 17, 15, 48, 57, 100000, tzinfo=_UTC)
    assert (epoch_ts["id_orig_h"], epoch_ts["orig_bytes"]) == ("192.168.4.76", 77)


def test_suricata_eve_json():
    (alert, dns), _ = rows("suricata_eve")
    assert alert["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (alert["event_type"], alert["alert_signature_id"], alert["alert_severity"]) == (
        "alert",
        2019401,
        1,
    )
    assert alert["http"]["http_user_agent"] == "Java/1.8.0_101"
    assert (dns["event_type"], dns["alert_signature"], dns["dns"]["rrname"]) == (
        "dns",
        None,
        "example.com",
    )


def test_snort_fast_alert_with_and_without_its_year():
    (java, icmp), _ = rows("snort_fast")
    assert java["timestamp"] == datetime(2026, 5, 11, 8, 15, 23, 456789, tzinfo=_LOCAL)
    assert (java["generator_id"], java["signature_id"], java["revision"]) == ("1", "2019401", "2")
    assert java["classification"] == "Potential Corporate Privacy Violation"
    assert (java["protocol"], java["src_ip"], java["src_port"], java["dst_port"]) == (
        "TCP",
        "192.168.1.10",
        51234,
        80,
    )
    assert icmp["timestamp"] == datetime(2023, 5, 11, 8, 15, 24, 1, tzinfo=_LOCAL)
    assert (icmp["classification"], icmp["src_port"]) == (None, None)


@pytest.mark.parametrize("name", ["snort_fast", "zeek_json", "suricata_eve"])
def test_a_line_in_another_form_is_refused(name):
    with pytest.raises(ParseError):
        BUILT_IN[name].parse("not a log line", _ctx())
