# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the web server and proxy log presets read the lines each project's documentation
gives (tests/unit/fixtures/logparse/web), one fixture per preset. nginx and Apache write their error
logs in local time, read in the zone of the file's last write."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "web"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str) -> list[dict]:
    fmt = BUILT_IN[name]
    ctx = _ctx()
    lines = (_FIXTURES / f"{name}.log").read_text().splitlines()
    return [row for line in lines if line.strip() for row in fmt.parse_many(line, ctx)]


def test_the_web_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in (
        "nginx_error",
        "apache_error",
        "haproxy_http",
        "squid_access",
        "envoy_access",
        "caddy_access",
        "traefik_access",
    ):
        assert names[name] == "web"


def test_nginx_error_log():
    failed, notice = rows("nginx_error")
    assert failed["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_LOCAL)
    assert (failed["level"], failed["pid"], failed["connection_id"]) == ("error", "1234", "5")
    assert failed["message"].startswith('open() "/usr/share/nginx/html/favicon.ico" failed')
    assert (failed["client"], failed["server"], failed["host"]) == (
        "192.168.1.10",
        "localhost",
        "example.com",
    )
    assert failed["request"] == "GET /favicon.ico HTTP/1.1"
    assert failed["referrer"] == "http://example.com/"
    assert (notice["level"], notice["message"], notice["client"]) == (
        "notice",
        "start worker processes",
        None,
    )


def test_apache_error_log():
    redirects, started = rows("apache_error")
    assert redirects["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 123456, tzinfo=_LOCAL)
    assert (redirects["module"], redirects["level"], redirects["pid"]) == ("core", "error", "1234")
    assert (redirects["client_ip"], redirects["client_port"]) == ("192.168.1.10", 51234)
    assert redirects["error_code"] == "AH00124"
    assert started["client_ip"] is None and started["module"] == "mpm_event"


def test_haproxy_http_log():
    (row,) = rows("haproxy_http")
    assert row["accept_date"] == datetime(2009, 2, 6, 12, 14, 14, 655000, tzinfo=_LOCAL)
    assert (row["process_pid"], row["client_ip"], row["client_port"]) == (
        "14389",
        "10.0.1.2",
        33317,
    )
    assert (row["frontend"], row["backend"], row["server"]) == ("http-in", "static", "srv1")
    assert (row["tr"], row["tw"], row["tc"], row["tr_server"], row["ta"]) == (
        "10",
        "0",
        "30",
        "69",
        "109",
    )
    assert (row["status_code"], row["bytes_read"], row["termination_state"]) == (
        "200",
        "2750",
        "----",
    )
    assert row["captured_request_cookie"] is None
    assert row["captured_request_headers"] == "1wt.eu"
    assert (row["method"], row["url"]) == ("GET", "/index.html")


def test_squid_native_access_log():
    hit, denied = rows("squid_access")
    assert hit["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 123000, tzinfo=_UTC)
    assert (hit["result_code"], hit["status_code"], hit["bytes"]) == ("TCP_MISS", "200", "4523")
    assert (hit["hierarchy_code"], hit["peer"], hit["user"]) == (
        "HIER_DIRECT",
        "93.184.216.34",
        None,
    )
    assert (denied["result_code"], denied["method"], denied["peer"]) == (
        "TCP_DENIED",
        "CONNECT",
        None,
    )


def test_envoy_default_access_log():
    (row,) = rows("envoy_access")
    assert row["start_time"] == datetime(2016, 4, 15, 20, 17, 0, 310000, tzinfo=_UTC)
    assert (row["method"], row["url"], row["protocol"]) == ("POST", "/api/v1/locations", "HTTP/2")
    assert (row["response_code"], row["response_flags"], row["duration_ms"]) == ("204", None, "226")
    assert (row["authority"], row["upstream_host"]) == ("locations", "tcp://10.0.2.1:80")


def test_caddy_structured_access_log():
    (row,) = rows("caddy_access")
    assert row["ts"] == datetime.fromtimestamp(1646861401.5241024, tz=_UTC)
    assert (row["method"], row["uri"], row["status"], row["size"]) == ("GET", "/", 200, 10900)
    assert row["remote_ip"] == "127.0.0.1" and row["user_id"] is None
    assert row["request"]["tls"]["server_name"] == "example.com"


def test_traefik_common_access_log():
    (row,) = rows("traefik_access")
    assert row["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_UTC)
    assert (row["method"], row["url"], row["status"]) == ("GET", "/api/orders", "200")
    assert (row["router"], row["service_url"], row["duration_ms"]) == (
        "orders@docker",
        "http://172.18.0.3:8080",
        "12",
    )
    assert row["referer"] is None


@pytest.mark.parametrize("name", ["nginx_error", "apache_error", "haproxy_http"])
def test_a_line_in_another_form_is_refused(name):
    with pytest.raises(ParseError):
        BUILT_IN[name].parse("not a log line", _ctx())
