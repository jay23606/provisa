# Copyright (c) 2026 Kenneth Stott
# Canary: 426cd1e8-6fa5-4a7c-a135-bf2d8deee857
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1997: how a database file's lock behaves between two processes on this OS -- what the
write refusal (``federation.file_locks``) rests on. Another process holds the file open; this
one tries. DuckDB locks a file for as long as it is open: read-only opens share, any other pair
excludes. SQLite locks per write transaction: with no wait, a write while another holds one is
refused at once."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb
import pytest


@contextmanager
def _held_elsewhere(code: str) -> Iterator[None]:
    """Another process running ``code``, which takes its hold and says so, then waits."""
    other = subprocess.Popen(
        [sys.executable, "-c", code + "\nprint('held', flush=True)\nimport time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert other.stdout is not None
        line = other.stdout.readline().strip()
        assert line == "held", line
        yield
    finally:
        other.kill()
        other.wait()


@pytest.fixture
def duck(tmp_path):
    path = tmp_path / "d.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1)")
    con.close()
    return str(path)


def _duck_holder(path: str, read_only: bool) -> str:
    return f"import duckdb\nc = duckdb.connect({path!r}, read_only={read_only})"


def test_duckdb_read_only_opens_share_a_file(duck):
    with _held_elsewhere(_duck_holder(duck, True)):
        con = duckdb.connect(duck, read_only=True)
        assert con.execute("SELECT a FROM t").fetchall() == [(1,)]
        con.close()


def test_duckdb_a_read_only_holder_keeps_a_read_write_open_out(duck):
    with _held_elsewhere(_duck_holder(duck, True)):
        with pytest.raises(duckdb.IOException, match="Could not set lock on file"):
            duckdb.connect(duck)


@pytest.mark.parametrize("read_only", [False, True])
def test_duckdb_a_read_write_holder_keeps_every_open_out(duck, read_only):
    with _held_elsewhere(_duck_holder(duck, False)):
        with pytest.raises(duckdb.IOException, match="Could not set lock on file"):
            duckdb.connect(duck, read_only=read_only)


def test_sqlite_a_write_while_another_process_writes_is_refused_at_once(tmp_path):
    path = str(tmp_path / "s.sqlite")
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE t (a INTEGER)")
    setup.commit()
    setup.close()
    holder = (
        f"import sqlite3\nc = sqlite3.connect({path!r})\n"
        "c.execute('BEGIN IMMEDIATE')\nc.execute('INSERT INTO t VALUES (1)')"
    )
    with _held_elsewhere(holder):
        con = sqlite3.connect(path, timeout=0)
        began = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            con.execute("INSERT INTO t VALUES (2)")
        assert time.monotonic() - began < 1.0  # no wait
        con.close()
    # The holder gone, the same write goes through.
    con = sqlite3.connect(path, timeout=0)
    con.execute("INSERT INTO t VALUES (2)")
    con.commit()
    assert con.execute("SELECT a FROM t").fetchall() == [(2,)]
    con.close()
