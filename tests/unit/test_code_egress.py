# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The egress proxy a sandboxed code source reaches the network through (REQ-1984, REQ-1993,
REQ-885): a host on the allow-list is reached by a CONNECT tunnel or a plain HTTP request; a host
off it, or loopback whatever the list says, is answered 403 naming it.

The upstream is a real server on this machine's own outward address (loopback is refused by
design, so it cannot stand in)."""

# Requirements: REQ-1984, REQ-1993, REQ-885
from __future__ import annotations

import socket
import threading

import pytest

from provisa.codesource.egress import EgressProxy

pytestmark = pytest.mark.unit


def _outward_address() -> str:
    """This machine's address on its default route (a UDP connect sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routed, never answered
        return probe.getsockname()[0]


@pytest.fixture
def upstream():
    """A server that records the first request it is sent and answers it."""
    address = _outward_address()
    server = socket.socket()
    server.bind((address, 0))
    server.listen(4)
    seen: list[bytes] = []

    def _serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(65536)
                seen.append(data)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")

    threading.Thread(target=_serve, daemon=True).start()
    yield address, server.getsockname()[1], seen
    server.close()


def _ask(proxy: EgressProxy, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as conn:
        conn.sendall(request)
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
            if request.startswith(b"CONNECT") and b"\r\n\r\n" in b"".join(chunks):
                break
        return b"".join(chunks)


def test_a_connect_to_a_host_on_the_list_is_tunnelled(upstream):
    host, port, seen = upstream
    proxy = EgressProxy([host])
    try:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as conn:
            conn.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
            assert conn.recv(4096).startswith(b"HTTP/1.1 200")
            conn.sendall(b"GET /through HTTP/1.1\r\nHost: x\r\n\r\n")
            answer = b""
            while chunk := conn.recv(4096):
                answer += chunk
        assert answer.endswith(b"ok")
        assert seen[0].startswith(b"GET /through HTTP/1.1")
    finally:
        proxy.stop()


def test_a_plain_request_is_sent_on_in_origin_form(upstream):
    host, port, seen = upstream
    proxy = EgressProxy([f"{host}:{port}"])
    try:
        answer = _ask(
            proxy, f"GET http://{host}:{port}/rates?d=1 HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
        )
        assert answer.endswith(b"ok")
        assert seen[0].startswith(b"GET /rates?d=1 HTTP/1.1\r\n")
    finally:
        proxy.stop()


def test_a_host_off_the_list_is_refused_by_name(upstream):
    host, port, seen = upstream
    proxy = EgressProxy(["api.example.test"])
    try:
        answer = _ask(proxy, f"CONNECT {host}:{port} HTTP/1.1\r\n\r\n".encode())
        assert answer.startswith(b"HTTP/1.1 403")
        assert f"egress to {host}:{port} is not on the egress allow-list".encode() in answer
        assert seen == []
    finally:
        proxy.stop()


def test_a_listed_host_on_another_port_is_refused(upstream):
    host, port, _seen = upstream
    proxy = EgressProxy([f"{host}:{port + 1}"])
    try:
        assert _ask(proxy, f"CONNECT {host}:{port} HTTP/1.1\r\n\r\n".encode()).startswith(
            b"HTTP/1.1 403"
        )
    finally:
        proxy.stop()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_is_never_reached_even_when_listed(host):
    proxy = EgressProxy([host])
    try:
        assert not proxy.admits(host, 5432)
    finally:
        proxy.stop()


def test_a_runtime_is_pointed_at_the_proxy():
    proxy = EgressProxy([])
    try:
        env = proxy.environment()
        assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == f"http://127.0.0.1:{proxy.port}"
        assert env["NODE_USE_ENV_PROXY"] == "1"
    finally:
        proxy.stop()
