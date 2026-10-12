# Copyright (c) 2026 Kenneth Stott
# Canary: 5a9e1c64-7f2b-4d38-b6e0-3c8d2f7a9b41
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Shutdown ends in-flight requests (REQ-1882, REQ-1905).

Every request runs on its own thread and its driver calls block that thread. A worker told to
stop (SIGTERM, SIGINT) waited for those requests, and a request inside a long run of statements
never looked up — the worker ignored the signal until the request finished on its own. On
shutdown every live request deadline is expired: the in-flight statement is cancelled through its
driver and the next one is refused, so the request fails with a clear error and the worker exits."""

# Requirements: REQ-1882, REQ-1905

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from provisa.core import request_deadline


def test_expiring_live_deadlines_cancels_the_statement_in_flight_and_refuses_the_next():
    cancelled: list[str] = []
    entered, release = threading.Event(), threading.Event()
    failure: list[BaseException] = []

    def _request() -> None:
        try:
            with request_deadline.within(300.0):
                with request_deadline.cancel_on_deadline(lambda: cancelled.append("a")):
                    entered.set()
                    release.wait(10)
                # the next statement of the same request
                with request_deadline.cancel_on_deadline(lambda: cancelled.append("b")):
                    raise AssertionError("a statement started after shutdown")
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=_request)
    thread.start()
    assert entered.wait(5)
    assert request_deadline.expire_all("the server is shutting down") == 1
    assert cancelled == ["a"], "the in-flight statement was not cancelled"
    release.set()
    thread.join(5)
    assert len(failure) == 1 and isinstance(failure[0], TimeoutError), failure
    assert "shutting down" in str(failure[0])
    assert cancelled == ["a"]


def test_a_finished_request_is_not_touched():
    with request_deadline.within(300.0):
        pass
    assert request_deadline.expire_all("the server is shutting down") == 0


def test_the_stop_signal_expires_live_deadlines_and_runs_the_servers_own_handler(monkeypatch):
    """The handler is chained in front of the one already installed (uvicorn's), which still
    runs. The deadlines are expired off the signal's path, on a thread of their own (#237)."""
    calls: list[object] = []
    expired: list[tuple[str, threading.Thread]] = []
    expiry = threading.Event()
    installed: dict[int, object] = {}
    previous = {
        signal.SIGTERM: lambda s, f: calls.append(("server", s)),
        signal.SIGINT: signal.SIG_DFL,
    }

    def _expire_all(reason: str) -> int:
        expired.append((reason, threading.current_thread()))
        expiry.set()
        return 0

    monkeypatch.setattr(signal, "getsignal", lambda sig: previous[sig])
    monkeypatch.setattr(signal, "signal", lambda sig, handler: installed.__setitem__(sig, handler))
    monkeypatch.setattr(request_deadline, "expire_all", _expire_all)
    with request_deadline.expire_on_stop_signals():
        assert set(installed) == {signal.SIGTERM, signal.SIGINT}
        installed[signal.SIGTERM](signal.SIGTERM, None)
        assert calls == [("server", signal.SIGTERM)]
        assert expiry.wait(10)
        ((reason, thread),) = expired
        assert "shutting down" in reason and thread is not threading.main_thread()
    # restored on the way out
    assert installed[signal.SIGTERM] is previous[signal.SIGTERM]
    assert installed[signal.SIGINT] is signal.SIG_DFL


def test_signal_chaining_is_skipped_off_the_main_thread():
    """Signal handlers can only be installed from the main thread; a lifespan run elsewhere (an
    in-process test client) installs nothing and raises nothing."""
    outcome: list[object] = []

    def _run() -> None:
        try:
            with request_deadline.expire_on_stop_signals():
                outcome.append(signal.getsignal(signal.SIGTERM))
        except BaseException as exc:
            outcome.append(exc)

    before = signal.getsignal(signal.SIGTERM)
    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(5)
    assert outcome == [before]


#: A stop signal that arrives while the main thread is inside the first one's expiry: the main
#: thread holds the live-deadline lock, as the first handler does mid-``expire_all``, and the
#: signal's handler runs on that same thread (#237).
_SIGNAL_MID_EXPIRY = """
import os, signal, time
from provisa.core import request_deadline

served = []
signal.signal(signal.SIGTERM, lambda s, f: served.append(s))
with request_deadline.expire_on_stop_signals():
    live = request_deadline.Deadline(300.0)
    with request_deadline._live_lock:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.2)  # the handler has run, on this thread, with the lock held
    while not live.ended_early:
        time.sleep(0.01)
print(served == [signal.SIGTERM], live.ended_early)
"""


def test_a_stop_signal_that_arrives_during_an_expiry_does_not_hang_the_main_thread():
    """The start script sends SIGINT and then SIGTERM. The second arrived while the first's
    handler held a lock its own thread then waited on, and the server never exited. The
    process is a fresh one so the signal reaches its main thread; a hang is its failure."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", _SIGNAL_MID_EXPIRY],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the main thread hung on a stop signal that arrived during an expiry")
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True"], done.stdout + done.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
