# Copyright (c) 2026 Kenneth Stott
# Canary: dc1134b5-61f0-490e-aae0-e9ee33c05a2f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The host lock works where there is no ``fcntl`` (Windows), through ``msvcrt.locking``: every
module that takes a file lock takes it through ``host_lock``, so importing provisa there no longer
dies with ``No module named 'fcntl'``. The lock is exclusive, offered without waiting, and released
on close."""

from __future__ import annotations

import errno
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from provisa.core import host_lock
from provisa.core.host_lock import FileLock, lock_fd, unlock_fd

_LOCKERS = (
    "provisa.encryption.providers",
    "provisa.core.org_folder_crypt",
    "provisa.federation.materialize_broker",
    "provisa.federation.replica_spool",
)


def test_the_modules_that_lock_a_file_import_where_there_is_no_fcntl():
    # A fresh interpreter: no fcntl to import, a stand-in msvcrt, and the host lock loaded as
    # Windows loads it. Each locking module then imports without reaching for fcntl itself.
    script = f"""
import sys, types
import errno, hashlib, os, tempfile  # host_lock's own imports, loaded for this platform first
import provisa.core.request_deadline
sys.modules["fcntl"] = None
sys.modules["msvcrt"] = types.SimpleNamespace(LK_NBLCK=2, LK_LOCK=1, LK_UNLCK=0, locking=None)
real, sys.platform = sys.platform, "win32"
import provisa.core.host_lock as hl
# The rest is loaded as this platform loads it: subprocess takes an importable msvcrt for Windows.
sys.platform = real
del sys.modules["msvcrt"]
assert hl._lock.__code__.co_names.count("msvcrt"), "the Windows lock was not the one loaded"
for name in {list(_LOCKERS)!r}:
    __import__(name)
print("ok")
"""
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        timeout=120,
    )
    assert done.stdout.strip() == "ok", done.stderr


def test_a_lock_is_exclusive_offered_without_waiting_and_freed_on_release(tmp_path):
    first, second = FileLock(tmp_path / "a.lock"), FileLock(tmp_path / "a.lock")
    assert first.try_acquire() is True
    assert second.try_acquire() is False  # held: never waits
    first.release()
    assert second.try_acquire() is True
    second.release()


def test_a_file_lock_is_freed_by_unlock_and_by_closing_its_file(tmp_path):
    path = tmp_path / "b.lock"
    holder = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    other = os.open(path, os.O_RDWR)
    try:
        assert lock_fd(holder, wait=True) is True
        assert lock_fd(other, wait=False) is False
        unlock_fd(holder)
        assert lock_fd(other, wait=False) is True
        os.close(other)  # closing the file releases its lock
        other = os.open(path, os.O_RDWR)
        assert lock_fd(holder, wait=False) is True
    finally:
        os.close(holder)
        os.close(other)


class _Msvcrt:
    """``msvcrt.locking`` as Windows answers it: a byte held by another file refuses a
    non-blocking lock with EACCES, and a blocking one gives up with EDEADLK after its tries."""

    LK_UNLCK, LK_LOCK, LK_NBLCK = 0, 1, 2

    def __init__(self, busy_for: int) -> None:
        self.busy_for = busy_for
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append((os.lseek(fd, 0, os.SEEK_CUR), mode, nbytes))
        if mode == self.LK_UNLCK:
            return
        if self.busy_for > 0:
            self.busy_for -= 1
            raise OSError(errno.EACCES if mode == self.LK_NBLCK else errno.EDEADLK, "locked")


@pytest.fixture
def windows(monkeypatch):
    """The host lock as Windows loads it, against a stand-in msvcrt; reloaded as it was after."""

    def load(fake: _Msvcrt):
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        monkeypatch.setattr(sys, "platform", "win32")
        return importlib.reload(host_lock)

    yield load
    monkeypatch.undo()
    importlib.reload(host_lock)


def test_on_windows_the_first_byte_is_locked_and_a_held_one_is_not_waited_for(windows, tmp_path):
    fake = _Msvcrt(busy_for=1)
    hl = windows(fake)
    fd = os.open(tmp_path / "c.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.write(fd, b"xyz")  # the position moves; the lock is still the first byte
        assert hl.lock_fd(fd, wait=False) is False  # held elsewhere: EACCES
        assert hl.lock_fd(fd, wait=False) is True
        hl.unlock_fd(fd)
    finally:
        os.close(fd)
    assert fake.calls == [(0, fake.LK_NBLCK, 1), (0, fake.LK_NBLCK, 1), (0, fake.LK_UNLCK, 1)]


def test_on_windows_a_waiting_lock_waits_past_msvcrts_own_tries(windows, tmp_path):
    fake = _Msvcrt(busy_for=2)  # LK_LOCK gives up twice, then the holder lets go
    hl = windows(fake)
    fd = os.open(tmp_path / "d.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        assert hl.lock_fd(fd, wait=True) is True
    finally:
        os.close(fd)
    assert [mode for _, mode, _ in fake.calls] == [fake.LK_LOCK] * 3
