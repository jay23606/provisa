# Copyright (c) 2026 Kenneth Stott
# Canary: 51feea2a-11bc-432c-b00c-039f3f11851a
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-1911: the server's CPU read from another host — the agent on the server's host answers the
same cumulative CPU seconds ``--server-pid`` reads locally, and nothing else."""

from __future__ import annotations

import argparse
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import psutil
import pytest

BENCH = Path(__file__).resolve().parents[3] / "demo" / "named" / "perf" / "bench"
sys.path.insert(0, str(BENCH))

import contract_model  # noqa: E402
import optimistic_load as ol  # noqa: E402
import server_cpu_agent as agent  # noqa: E402


@pytest.fixture
def url() -> Iterator[str]:
    server = agent.serve(os.getpid(), ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()


def test_the_agent_answers_the_pids_cumulative_cpu_seconds(url: str) -> None:
    before = agent.cpu_seconds(os.getpid())
    body = httpx.get(url).json()
    after = agent.cpu_seconds(os.getpid())
    assert set(body) == {"pid", "cpu_seconds"}
    assert body["pid"] == os.getpid()
    assert before <= body["cpu_seconds"] <= after


def test_the_run_reads_the_same_figure_through_the_url(url: str) -> None:
    before = ol._server_cpu_seconds(os.getpid())
    remote = ol._server_cpu_seconds(url)
    after = ol._server_cpu_seconds(os.getpid())
    assert before is not None and remote is not None and after is not None
    assert before <= remote <= after


def test_the_agent_answers_nothing_else(url: str) -> None:
    assert httpx.get(url + "anything").status_code == 404
    assert httpx.post(url, content=b"{}").status_code == 501


def test_the_agent_needs_an_explicit_listen_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["server_cpu_agent.py", "--pid", str(os.getpid())])
    with pytest.raises(SystemExit):
        agent.main()


@pytest.mark.parametrize("value", ["9555", ":9555", "host:", "host:port"])
def test_a_listen_value_that_is_not_host_and_port_is_refused(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="--listen must be HOST:PORT"):
        agent.parse_listen(value)


def test_listen_accepts_a_host_and_a_port() -> None:
    assert agent.parse_listen("10.0.0.5:9555") == ("10.0.0.5", 9555)
    assert agent.parse_listen("[fd00::5]:9555") == ("fd00::5", 9555)


def test_the_agent_refuses_a_pid_that_is_not_running() -> None:
    gone = max(psutil.pids()) + 100_000
    with pytest.raises(psutil.NoSuchProcess):
        agent.serve(gone, ("127.0.0.1", 0))


def _args(pid: int | None, url: str | None) -> argparse.Namespace:
    return argparse.Namespace(server_pid=pid, server_cpu_url=url)


def test_the_server_cpu_comes_from_the_pid_or_the_url_not_both() -> None:
    assert ol.server_cpu_source(_args(42, None)) == 42
    assert ol.server_cpu_source(_args(None, "http://10.0.0.5:9555/")) == "http://10.0.0.5:9555/"
    assert ol.server_cpu_source(_args(None, None)) is None
    with pytest.raises(contract_model.SetupError, match="give one, not both"):
        ol.server_cpu_source(_args(42, "http://10.0.0.5:9555/"))
