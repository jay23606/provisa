# Copyright (c) 2026 Kenneth Stott
# Canary: 321227f5-d531-4a38-ad27-380b7987e9f3
#
# This source code is licensed under the Business Source License 1.1
"""A write to a DuckDB database file (REQ-1997).

The maintainer's ruling: "writes back to file databases in a multi-node env - just error them
out when they can't a lock on it." DuckDB locks a database file for as long as it is open: a
read-write open excludes every other open, a read-only one shares with other read-only opens
only. So every holder in a process -- the engine's attach, a driver's connection -- keeps a
local file open read-only, and reads go on on every node. A write pauses this process's holders
of the file (:func:`exclusive`), opens it read-write for its statement alone and closes it; when
that open cannot take the lock (another process or node has the file open), the write is refused
naming the source and that its file is locked -- no wait, no queue.

A holder is registered by the file's resolved path with a context manager factory: entered, it
lets go of the file; left, it opens it again (the engine detaches and re-attaches under its
catalogue gate, so a query in flight finishes first and none runs while the file is away)."""

# Requirements: REQ-1997
from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager

Pause = Callable[[], AbstractContextManager[None]]

_guard = threading.Lock()
_holders: dict[str, dict[int, Pause]] = {}
_file_locks: dict[str, threading.Lock] = {}


class ReadersWriterGate:
    """Many readers or one writer, never both; a waiting writer does not hold back new readers
    (the engine's catalogue gate takes it so, ``duckdb_runtime._CatalogGate``)."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writing = False

    def acquire_read(self) -> None:
        with self._cond:
            while self._writing:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    @contextmanager
    def read(self):
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write(self):
        with self._cond:
            while self._writing or self._readers:
                self._cond.wait()
            self._writing = True
        try:
            yield
        finally:
            with self._cond:
                self._writing = False
                self._cond.notify_all()


class FileLocked(RuntimeError):
    """A write refused because its database file is open elsewhere."""

    def __init__(self, path: str, source_id: str | None = None) -> None:
        self.path = path
        self.source_id = source_id
        who = f"source {source_id!r}" if source_id else "the source"
        super().__init__(
            f"the write to {who} is refused: its file {path} is locked -- another process or "
            "node has it open"
        )

    def of(self, source_id: str) -> FileLocked:
        return FileLocked(self.path, source_id)


def key(path: str) -> str:
    return os.path.realpath(path)


def register(path: str, pause: Pause) -> int:
    """Register a holder of the file at ``path``; the token to :func:`unregister` it with."""
    with _guard:
        holders = _holders.setdefault(key(path), {})
        token = id(pause)
        holders[token] = pause
        return token


def unregister(path: str, token: int) -> None:
    with _guard:
        holders = _holders.get(key(path))
        if holders is not None:
            holders.pop(token, None)


def _file_lock(path: str) -> threading.Lock:
    with _guard:
        return _file_locks.setdefault(key(path), threading.Lock())


@contextmanager
def exclusive(path: str) -> Iterator[None]:
    """Hold the file at ``path`` alone in this process: one write at a time, every registered
    holder paused while it runs and resumed after."""
    with _file_lock(path), ExitStack() as paused:
        with _guard:
            pauses = list(_holders.get(key(path), {}).values())
        for pause in pauses:
            paused.enter_context(pause())
        yield


class UnprotectedWrite(RuntimeError):
    """A write to a database file in an encrypted org folder on a mount shared by several nodes:
    the encryption layer (gocryptfs) does not pass an application's file locks to the shared
    storage, so nothing would keep two nodes from writing the file at once."""

    def __init__(self, path: str, source_id: str | None = None) -> None:
        self.path = path
        self.source_id = source_id
        who = f"source {source_id!r}" if source_id else "the source"
        super().__init__(
            f"the write to {who} is refused: its file {path} is in an encrypted org folder shared "
            "by several nodes, where its lock does not reach the other nodes"
        )

    def of(self, source_id: str) -> UnprotectedWrite:
        return UnprotectedWrite(self.path, source_id)


def refuse_unprotected(path: str, shown: str | None = None) -> None:
    """Refuse a write to the database file at ``path`` when no lock can protect it: the org
    folder it is in is encrypted and its mount is shared (``org_files.shared_mount``). The
    refusal names the file as ``shown`` (the source's own path, an org token kept as written)."""
    from provisa.core import org_files, org_folder_crypt

    if not org_files.shared_mount():
        return
    real = key(path)
    orgs = key(str(org_files.orgs_dir()))
    if not real.startswith(orgs + os.sep):
        return
    org = real[len(orgs) + 1 :].split(os.sep, 1)[0]
    if org_folder_crypt.is_encrypted(org_files.orgs_dir() / org):
        raise UnprotectedWrite(shown or path)


def is_lock_conflict(exc: BaseException) -> bool:
    """Whether DuckDB refused to open a file because another open holds its lock. DuckDB states
    it only in the IO error's text."""
    return "Could not set lock on file" in str(exc)
