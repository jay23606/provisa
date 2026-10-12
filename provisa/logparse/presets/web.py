# Copyright (c) 2026 Kenneth Stott
# Canary: 0933223e-074d-44c6-b631-89db96fc7d04
#
# This source code is licensed under the Business Source License 1.1
"""Web server and proxy log presets (REQ-1996): nginx and Apache error logs, HAProxy's HTTP log,
Squid's native access log, Envoy's default access log, Caddy's structured access log and Traefik's
access log, each in the form its documentation gives. nginx and Apache write their error logs in
the server's local time, read in the zone of the file's last write."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from provisa.logparse.base import Column, FileContext, Format, ParseError
from provisa.logparse.formats import RegexFormat
from provisa.logparse.presets._shared import (
    JsonFormat,
    TokenFormat,
    epoch,
    host_port,
    request_parts,
    utc,
)

GROUP = "web"


def _local(stamp: str, fmt: str, ctx: FileContext) -> datetime:
    try:
        return datetime.strptime(stamp, fmt).replace(tzinfo=ctx.mtime.tzinfo)
    except ValueError as exc:
        raise ParseError(f"not a timestamp: {stamp!r}") from exc


# --- nginx error log ---------------------------------------------------------------------------


def _nginx_error(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    return {
        "timestamp": _local(g["time"] or "", "%Y/%m/%d %H:%M:%S", ctx),
        "level": g["level"],
        "pid": g["pid"],
        "tid": g["tid"],
        "connection_id": g["cid"],
        "message": g["message"],
        "client": g["client"],
        "server": g["server"],
        "request": g["request"],
        "upstream": g["upstream"],
        "host": g["host"],
        "referrer": g["referrer"],
    }


NGINX_ERROR = RegexFormat(
    "nginx_error",
    "nginx error log",
    GROUP,
    r"^(?P<time>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>\w+)\] (?P<pid>\d+)#(?P<tid>\d+): "
    r"(?:\*(?P<cid>\d+) )?(?P<message>.*?)(?:, client: (?P<client>[^,]+))?"
    r'(?:, server: (?P<server>[^,]*))?(?:, request: "(?P<request>[^"]*)")?'
    r'(?:, upstream: "(?P<upstream>[^"]*)")?(?:, host: "(?P<host>[^"]*)")?'
    r'(?:, referrer: "(?P<referrer>[^"]*)")?$',
    [
        Column("timestamp", "timestamp"),
        Column("level", "string"),
        Column("pid", "integer"),
        Column("tid", "integer"),
        Column("connection_id", "integer"),
        Column("message", "string"),
        Column("client", "string"),
        Column("server", "string"),
        Column("request", "string"),
        Column("upstream", "string"),
        Column("host", "string"),
        Column("referrer", "string"),
    ],
    _nginx_error,
)

# --- Apache httpd error log (2.4) --------------------------------------------------------------


def _apache_error(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    stamp = g["time"] or ""
    fmt = "%a %b %d %H:%M:%S.%f %Y" if "." in stamp else "%a %b %d %H:%M:%S %Y"
    client_ip, client_port = host_port(g["client"])
    return {
        "timestamp": _local(stamp, fmt, ctx),
        "module": g["module"],
        "level": g["level"],
        "pid": g["pid"],
        "tid": g["tid"],
        "client_ip": client_ip,
        "client_port": client_port,
        "error_code": g["code"],
        "message": g["message"],
    }


APACHE_ERROR = RegexFormat(
    "apache_error",
    "Apache httpd error log",
    GROUP,
    r"^\[(?P<time>[A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? \d{4})\] "
    r"\[(?:(?P<module>[^:\]]+):)?(?P<level>[^\]]+)\] \[pid (?P<pid>\d+)(?::tid (?P<tid>\d+))?\]"
    r"(?: \[client (?P<client>[^\]]+)\])? (?:(?P<code>AH\d+): )?(?P<message>.*)$",
    [
        Column("timestamp", "timestamp"),
        Column("module", "string"),
        Column("level", "string"),
        Column("pid", "integer"),
        Column("tid", "integer"),
        Column("client_ip", "string"),
        Column("client_port", "integer"),
        Column("error_code", "string"),
        Column("message", "string"),
    ],
    _apache_error,
)

# --- HAProxy HTTP log --------------------------------------------------------------------------


def _haproxy(g: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    client_ip, client_port = host_port(g["client"])
    timers = (g["timers"] or "").split("/")
    conns = (g["conns"] or "").split("/")
    queues = (g["queues"] or "").split("/")
    request = g["request"]
    return {
        "accept_date": _local(g["accept_date"] or "", "%d/%b/%Y:%H:%M:%S.%f", ctx),
        "process_pid": g["pid"],
        "client_ip": client_ip,
        "client_port": client_port,
        "frontend": g["frontend"],
        "backend": g["backend"],
        "server": g["server"],
        "tr": timers[0],
        "tw": timers[1],
        "tc": timers[2],
        "tr_server": timers[3],
        "ta": timers[4],
        "status_code": g["status"],
        "bytes_read": g["bytes"],
        "captured_request_cookie": None if g["req_cookie"] == "-" else g["req_cookie"],
        "captured_response_cookie": None if g["resp_cookie"] == "-" else g["resp_cookie"],
        "termination_state": g["termination"],
        "actconn": conns[0],
        "feconn": conns[1],
        "beconn": conns[2],
        "srv_conn": conns[3],
        "retries": conns[4].lstrip("+"),
        "srv_queue": queues[0],
        "backend_queue": queues[1],
        "captured_request_headers": g["req_headers"],
        "captured_response_headers": g["resp_headers"],
        "request": request,
        **request_parts(request),
    }


HAPROXY = RegexFormat(
    "haproxy_http",
    "HAProxy HTTP log",
    GROUP,
    # The syslog header HAProxy's messages carry when they reach a file, then its HTTP format.
    r"^(?:[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} \S+ )?(?:haproxy\[(?P<pid>\d+)\]: )?"
    r"(?P<client>\S+) \[(?P<accept_date>[^\]]+)\] (?P<frontend>\S+) (?P<backend>[^/\s]+)/"
    r"(?P<server>\S+) (?P<timers>-?\d+/-?\d+/-?\d+/-?\d+/\+?-?\d+) (?P<status>-?\d+) "
    r"(?P<bytes>\+?\d+) (?P<req_cookie>\S+) (?P<resp_cookie>\S+) (?P<termination>\S{4}) "
    r"(?P<conns>\d+/\d+/\d+/\d+/\+?\d+) (?P<queues>\d+/\d+)"
    r'(?: \{(?P<req_headers>[^}]*)\})?(?: \{(?P<resp_headers>[^}]*)\})? "(?P<request>[^"]*)"$',
    [
        Column("accept_date", "timestamp"),
        Column("process_pid", "integer"),
        Column("client_ip", "string"),
        Column("client_port", "integer"),
        Column("frontend", "string"),
        Column("backend", "string"),
        Column("server", "string"),
        Column("tr", "integer"),
        Column("tw", "integer"),
        Column("tc", "integer"),
        Column("tr_server", "integer"),
        Column("ta", "integer"),
        Column("status_code", "integer"),
        Column("bytes_read", "integer"),
        Column("captured_request_cookie", "string"),
        Column("captured_response_cookie", "string"),
        Column("termination_state", "string"),
        Column("actconn", "integer"),
        Column("feconn", "integer"),
        Column("beconn", "integer"),
        Column("srv_conn", "integer"),
        Column("retries", "integer"),
        Column("srv_queue", "integer"),
        Column("backend_queue", "integer"),
        Column("captured_request_headers", "string"),
        Column("captured_response_headers", "string"),
        Column("request", "string"),
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
    ],
    _haproxy,
)

# --- Squid native access log -------------------------------------------------------------------


def _squid(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    code, _, status = (f["result"] or "").partition("/")
    hierarchy, _, peer = (f["hierarchy"] or "").partition("/")
    return {
        "timestamp": epoch(f["time"]),
        "elapsed_ms": f["elapsed"],
        "client": f["client"],
        "result_code": code or None,
        "status_code": status or None,
        "bytes": f["bytes"],
        "method": f["method"],
        "url": f["url"],
        "user": f["user"],
        "hierarchy_code": hierarchy or None,
        "peer": None if peer in ("", "-") else peer,
        "content_type": f["type"],
    }


SQUID = TokenFormat(
    "squid_access",
    "Squid access log (native)",
    GROUP,
    ["time", "elapsed", "client", "result", "bytes", "method", "url", "user", "hierarchy", "type"],
    [
        Column("timestamp", "timestamp"),
        Column("elapsed_ms", "integer"),
        Column("client", "string"),
        Column("result_code", "string"),
        Column("status_code", "integer"),
        Column("bytes", "integer"),
        Column("method", "string"),
        Column("url", "string"),
        Column("user", "string"),
        Column("hierarchy_code", "string"),
        Column("peer", "string"),
        Column("content_type", "string"),
    ],
    _squid,
)

# --- Envoy default access log ------------------------------------------------------------------


def _envoy(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    request = f["request"]
    return {
        "start_time": utc(f["start_time"]),
        "request": request,
        **request_parts(request),
        "response_code": f["response_code"],
        "response_flags": f["response_flags"],
        "bytes_received": f["bytes_received"],
        "bytes_sent": f["bytes_sent"],
        "duration_ms": f["duration"],
        "upstream_service_time_ms": f["upstream_service_time"],
        "x_forwarded_for": f["x_forwarded_for"],
        "user_agent": f["user_agent"],
        "request_id": f["request_id"],
        "authority": f["authority"],
        "upstream_host": f["upstream_host"],
    }


ENVOY = TokenFormat(
    "envoy_access",
    "Envoy access log (default format)",
    GROUP,
    [
        "start_time",
        "request",
        "response_code",
        "response_flags",
        "bytes_received",
        "bytes_sent",
        "duration",
        "upstream_service_time",
        "x_forwarded_for",
        "user_agent",
        "request_id",
        "authority",
        "upstream_host",
    ],
    [
        Column("start_time", "timestamp"),
        Column("request", "string"),
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
        Column("response_code", "integer"),
        Column("response_flags", "string"),
        Column("bytes_received", "integer"),
        Column("bytes_sent", "integer"),
        Column("duration_ms", "integer"),
        Column("upstream_service_time_ms", "integer"),
        Column("x_forwarded_for", "string"),
        Column("user_agent", "string"),
        Column("request_id", "string"),
        Column("authority", "string"),
        Column("upstream_host", "string"),
    ],
    _envoy,
)

# --- Caddy structured access log ---------------------------------------------------------------

CADDY = JsonFormat(
    "caddy_access",
    "Caddy access log",
    GROUP,
    [
        (Column("ts", "timestamp"), "ts"),
        (Column("level", "string"), "level"),
        (Column("logger", "string"), "logger"),
        (Column("msg", "string"), "msg"),
        (Column("remote_ip", "string"), "request.remote_ip"),
        (Column("remote_port", "integer"), "request.remote_port"),
        (Column("proto", "string"), "request.proto"),
        (Column("method", "string"), "request.method"),
        (Column("host", "string"), "request.host"),
        (Column("uri", "string"), "request.uri"),
        (Column("request", "json"), "request"),
        (Column("user_id", "string"), "user_id"),
        (Column("duration_s", "float"), "duration"),
        (Column("size", "integer"), "size"),
        (Column("status", "integer"), "status"),
        (Column("resp_headers", "json"), "resp_headers"),
    ],
    lambda row, doc: {**row, "ts": epoch(row["ts"]), "user_id": row["user_id"] or None},
)

# --- Traefik access log (common format) --------------------------------------------------------


def _traefik(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    duration = f["duration"] or ""
    if duration and not duration.endswith("ms"):
        raise ParseError(f"a duration not in milliseconds: {duration!r}")
    request = f["request"]
    return {
        "client": f["client"],
        "ident": f["ident"],
        "user": f["user"],
        "timestamp": utc(f["time"], "%d/%b/%Y:%H:%M:%S %z"),
        "request": request,
        **request_parts(request),
        "status": f["status"],
        "size": f["size"],
        "referer": f["referer"],
        "user_agent": f["user_agent"],
        "request_count": f["request_count"],
        "router": f["router"],
        "service_url": f["service_url"],
        "duration_ms": duration[:-2] if duration else None,
    }


TRAEFIK = TokenFormat(
    "traefik_access",
    "Traefik access log (common format)",
    GROUP,
    [
        "client",
        "ident",
        "user",
        "time",
        "request",
        "status",
        "size",
        "referer",
        "user_agent",
        "request_count",
        "router",
        "service_url",
        "duration",
    ],
    [
        Column("client", "string"),
        Column("ident", "string"),
        Column("user", "string"),
        Column("timestamp", "timestamp"),
        Column("request", "string"),
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
        Column("status", "integer"),
        Column("size", "integer"),
        Column("referer", "string"),
        Column("user_agent", "string"),
        Column("request_count", "integer"),
        Column("router", "string"),
        Column("service_url", "string"),
        Column("duration_ms", "integer"),
    ],
    _traefik,
)

PRESETS: list[Format] = [NGINX_ERROR, APACHE_ERROR, HAPROXY, SQUID, ENVOY, CADDY, TRAEFIK]
