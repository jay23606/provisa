# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Python source read and served inside the worker's sandbox (REQ-1993): the reader imports the
code under the sandbox and its tables, commands and streams are the shared manifest's; the host
serves rows sandboxed; the code reads nothing outside it and reaches the network only through the
egress proxy, to the hosts on the allow-list.

The interpreter is this process's base Python (part P2 pins the source's own)."""

# Requirements: REQ-1993
from __future__ import annotations

import shutil
import socket
import sys
import threading
from pathlib import Path

import pytest

from provisa.codesource import worker as w
from provisa.codesource.manifest import Named, Scalar
from provisa.python.source import host_command, read_code

pytestmark = [pytest.mark.integration]

FIXTURE = Path(__file__).parent.parent / "fixtures" / "python_source"
PYTHON_HOME = Path(sys.base_prefix).resolve()


def _interpreter() -> Path:
    """This process's base interpreter itself. A macOS framework build's ``bin/python3`` only
    starts another program (``Python.app``), which the sandbox, which runs one program, refuses;
    that program is the interpreter. (The source's pinned Python, part P2, is a plain one.)"""
    app = PYTHON_HOME / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    if app.is_file():
        return app
    return Path(getattr(sys, "_base_executable", sys.executable)).resolve()


PYTHON = _interpreter()


@pytest.fixture
def code(tmp_path):
    copied = tmp_path / "code"
    shutil.copytree(FIXTURE, copied)
    return copied


def _start(code: Path, egress=()) -> w.Worker:
    command = host_command(
        python=PYTHON, python_home=PYTHON_HOME, code=code, entry="orders", egress=list(egress)
    )
    started = w.Worker("python-src", "h", command)
    started.start()
    return started


def test_the_code_is_read_inside_the_sandbox(code):
    manifest = read_code(python=PYTHON, python_home=PYTHON_HOME, code=code, entry="orders")
    orders = manifest.export("orders")
    assert orders.returns == Named("Order")
    assert [(p.name, p.shape) for p in orders.parameters] == [
        ("customer_id", Scalar("text")),
        ("since", Scalar("timestamp")),
    ]


def test_rows_are_served_inside_the_sandbox(code):
    started = _start(code)
    try:
        [[row]] = list(started.rows("orders", "table", ["acme"]))
        assert row["lines"] == [{"sku": "acme", "qty": 2}]
        assert [len(b) for b in started.rows("many", "table", [1500])] == [1000, 500]
    finally:
        started.stop()


def test_the_code_reads_nothing_outside_it(code):
    started = _start(code)
    try:
        with pytest.raises(w.CodeFailed, match="PermissionError|Operation not permitted"):
            list(started.rows("outside", "table", []))
    finally:
        started.stop()


def _outward_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routed, never answered
        return probe.getsockname()[0]


@pytest.fixture
def upstream():
    server = socket.socket()
    server.bind((_outward_address(), 0))
    server.listen(8)

    def _serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")

    threading.Thread(target=_serve, daemon=True).start()
    yield server.getsockname()
    server.close()


def test_a_host_on_the_allow_list_is_reached_through_the_proxy_and_no_other(code, upstream):
    host, port = upstream
    started = _start(code, egress=[f"{host}:{port}"])
    try:
        [[reached]] = list(started.rows("fetched", "table", [f"http://{host}:{port}/rates"]))
        assert reached == {"status": 200, "body": "ok"}
        [[refused]] = list(started.rows("fetched", "table", [f"http://{host}:{port + 1}/x"]))
        assert refused["status"] == 403
        assert "not on the egress allow-list" in refused["body"]
        with pytest.raises(w.CodeFailed):
            list(started.rows("direct", "table", [host, port]))  # around the proxy
    finally:
        started.stop()
