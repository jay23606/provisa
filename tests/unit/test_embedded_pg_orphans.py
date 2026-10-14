# Copyright (c) 2026 Kenneth Stott
# Canary: 2b7e4a5b-9478-4e36-9449-a238ecf66a29
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""A test session's embedded Postgres does not outlive the session that started it.

A session ended by a signal (a job stopped, a runner's timeout) never runs its fixtures' teardown,
and the Postgres it started kept running, holding the machine's shared memory, until no further
one could start ("could not create shared memory segment: No space left on device"). Each one now
records the process that started it, and the next start stops every one whose starter is gone; a
running session's is left alone."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tests.embedded_pg import start_local_postgres

_REPO = Path(__file__).resolve().parents[2]

_STARTER = """
import sys, time
sys.path.insert(0, {repo!r})
from tests.embedded_pg import start_local_postgres
pg = start_local_postgres()
print(pg.root, flush=True)
time.sleep(600)
"""


def _postmaster(root: Path) -> int | None:
    pid_file = root / "data" / "postmaster.pid"
    return int(pid_file.read_text().splitlines()[0]) if pid_file.exists() else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_elsewhere() -> tuple[subprocess.Popen, Path]:
    """A process that starts an embedded Postgres and holds it, as a test session does."""
    starter = subprocess.Popen(
        [sys.executable, "-c", _STARTER.format(repo=str(_REPO))],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert starter.stdout is not None
    return starter, Path(starter.stdout.readline().strip())


def test_a_postgres_whose_session_was_killed_is_stopped_by_the_next_start():
    starter, orphan_root = _start_elsewhere()
    postmaster = _postmaster(orphan_root)
    assert postmaster is not None and _alive(postmaster)
    starter.send_signal(signal.SIGTERM)  # no teardown runs: the session simply ends
    starter.wait(timeout=30)
    assert _alive(postmaster)  # what leaked before

    pg = start_local_postgres()
    try:
        deadline = time.monotonic() + 30
        while _alive(postmaster) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(postmaster)
        assert not orphan_root.exists()
    finally:
        pg.stop()


def test_a_running_session_s_postgres_is_left_alone():
    starter, root = _start_elsewhere()
    try:
        postmaster = _postmaster(root)
        pg = start_local_postgres()
        pg.stop()
        assert postmaster is not None and _alive(postmaster)
        assert root.exists()
    finally:
        starter.send_signal(signal.SIGTERM)
        starter.wait(timeout=30)
        start_local_postgres().stop()  # and it is reaped once its session is gone
    assert not root.exists()
