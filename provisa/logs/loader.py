# Copyright (c) 2026 Kenneth Stott
# Canary: 897937a6-b117-45dc-b19d-4ac72965b7d2
#
# This source code is licensed under the Business Source License 1.1
"""The table of a Logs source (REQ-1996), landed as a replica.

A replica is kept in place a part at a time (``federation.mail_units``): each pass reads every
file the glob matches from where the last pass reached in it, and writes its new records' rows
by their key -- the file's identity and the record's offset -- then keeps where it reached, in
that order: a pass that stops between the two reads those records again, and writing them again
leaves the same rows. A file no longer matched is forgotten; its rows stay, as a log's history.
What a pass reached is kept in the organisation's state store, beside a mail source's
(``federation.mail_sync_state``: one row per file, its identity in place of a mailbox).

A whole copy (the first build of a changed definition) reads every file from its start, and
keeps where it reached once the build is recorded as completed."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

from provisa.core import settings_registry
from provisa.logs import KEY, LANDED_AT, SCHEMA
from provisa.logs import settings as logs_settings
from provisa.logs.files import FileState, Found, Table, identify, matched, read_file
from provisa.logs.roots import checked_glob

#: How many rows a part of a pass writes together.
BATCH_ROWS = 5000

_DONE: Any = object()


def source_settings(source: Any) -> logs_settings.LogsSettings:
    return logs_settings.parse(dict(getattr(source, "mapping", None) or {}))


def _table(name: str, columns: list[tuple[str, str]]) -> Table:
    return Table(name, dict(columns), int(settings_registry.value("logs.max_line_bytes")))


async def _stepped(make: Any) -> AsyncIterator[Any]:
    """A blocking generator's items, each made off the event loop."""
    iterator = make()
    while True:
        item = await asyncio.to_thread(next, iterator, _DONE)
        if item is _DONE:
            return
        yield item


async def _found(source: Any, kept: dict[str, FileState]) -> tuple[list[Found], list[str]]:
    glob = checked_glob(source_settings(source).glob)
    return await asyncio.to_thread(lambda: identify(matched(glob), kept))


def _rows_of(found: Found, source: Any, table: Table) -> Iterator[list[dict[str, Any]]]:
    return read_file(found, source_settings(source).parser(), table, BATCH_ROWS)


class _UnitsRead:
    """One pass over a source's files that gives their new records as units to be written in
    place (``federation.mail_units.ReplicaUnitJob``): one unit a batch of a file's rows, which
    keeps where the file was read to once its rows are written. ``total`` is how many files the
    pass reads, known once it has begun."""

    unit = "files"
    committed = None  # each part keeps where it reached as it is written

    def __init__(
        self,
        state: Any,
        source: Any,
        tables: tuple[str, ...],
        columns: dict[str, list[tuple[str, str]]],
    ) -> None:
        if len(tables) != 1:
            raise ValueError(f"a Logs source has one table; asked for {', '.join(tables)}")
        self._state = state
        self._source = source
        self._name = tables[0]
        self._table = _table(self._name, columns[self._name])
        self.total = 0

    def notes(self) -> list[Any]:
        return []

    async def keep(self, account: str, links: dict[str, str]) -> None:
        from provisa.federation import mail_sync_state

        async with self._state.tenant_db.acquire() as conn:
            await mail_sync_state.keep_links(conn, self._source.id, account, links)

    async def forget(self, account: str) -> None:
        from provisa.federation import mail_sync_state

        async with self._state.tenant_db.acquire() as conn:
            await mail_sync_state.forget_account(conn, self._source.id, account)

    async def units(self) -> AsyncIterator[Any]:
        from provisa.core.canonical_mail import Unit
        from provisa.federation import mail_sync_state

        async with self._state.tenant_db.acquire() as conn:
            links = await mail_sync_state.links_of(conn, self._source.id)
        kept = {
            account: FileState.of(scopes[""]) for account, scopes in links.items() if "" in scopes
        }
        files, gone = await _found(self._source, kept)
        self.total = len(files)
        for file_id in gone:
            yield Unit(file_id, forget=True)
        for found in files:
            async for rows in _stepped(
                lambda found=found: _rows_of(found, self._source, self._table)
            ):
                yield Unit(found.state.id, rows={self._name: rows}, links={"": found.state.token()})
            yield Unit(found.state.id, links={"": found.state.token()}, last=True)


class _WholeRead:
    """One read of every file from its start, as the rows of the source's table: what a whole
    build streams (``federation.data_replicator.ReplicaGroupJob``)."""

    def __init__(
        self,
        state: Any,
        source: Any,
        tables: tuple[str, ...],
        columns: dict[str, list[tuple[str, str]]],
    ) -> None:
        from provisa.federation.data_replicator import SourceCaps, SourceRead

        if len(tables) != 1:
            raise ValueError(f"a Logs source has one table; asked for {', '.join(tables)}")
        self.caps = SourceCaps(frozenset({SourceRead.CURSOR}))
        self._state = state
        self._source = source
        self._name = tables[0]
        self._columns = columns[self._name]
        self._reached: list[FileState] = []

    def notes(self) -> list[Any]:
        return []

    async def batches(self, batch_rows: int) -> AsyncIterator[tuple[str, Any]]:
        from provisa.core.ir_arrow import arrow_schema, rows_to_batch

        self._reached.clear()
        schema = arrow_schema(self._columns)
        table = _table(self._name, self._columns)
        at = datetime.now(UTC).replace(tzinfo=None)  # one whole build lands together
        files, _gone = await _found(self._source, {})
        for found in files:
            async for rows in _stepped(lambda found=found: _rows_of(found, self._source, table)):
                for row in rows:
                    row[LANDED_AT] = at
                for start in range(0, len(rows), batch_rows):
                    yield (
                        self._name,
                        rows_to_batch(rows[start : start + batch_rows], self._columns, schema),
                    )
            self._reached.append(found.state)

    async def committed(self) -> None:
        """Keep where this read reached in each file, now that the build it fed is recorded as
        completed, in place of everything kept before."""
        from provisa.federation import mail_sync_state

        rows = {(s.id, "", mail_sync_state.DELTA): s.token() for s in self._reached}
        async with self._state.tenant_db.acquire() as conn:
            await mail_sync_state.replace(conn, self._source.id, rows)


def files_token(source: Any) -> str:
    """What the matched files are now: a digest of each one's name, inode, size and last write.
    An equal token is files nothing was written to."""
    glob = checked_glob(source_settings(source).glob)
    digest = hashlib.sha256()
    for path in matched(glob):
        stat = os.stat(path)
        digest.update(f"{path}\0{stat.st_ino}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def make_logs_loader(state: Any) -> Any:
    """The Logs source's row fetch and replica reads (REQ-1996)."""

    async def _load(source: Any, table: Any) -> list[dict]:
        """Every record of the files as rows: the source's whole table, as it stands."""
        reading = _table(table.table_name, [(c.name, c.data_type) for c in table.columns])
        out: list[dict] = []
        files, _gone = await _found(source, {})
        for found in files:
            async for rows in _stepped(lambda found=found: _rows_of(found, source, reading)):
                out.extend(rows)
        return out

    def _replica_group(_source: Any, table: Any) -> tuple[str, ...]:
        return (table.table_name,)

    def _freshness_probe(source: Any, _table_: Any) -> Any:
        async def token() -> str | None:
            return await asyncio.to_thread(files_token, source)

        return token

    _load.replica_group = _replica_group  # type: ignore[attr-defined]
    _load.replica_group_source = lambda source, tables, columns: _WholeRead(  # type: ignore[attr-defined]
        state, source, tuple(tables), columns
    )
    _load.replica_unit_source = lambda source, tables, columns: _UnitsRead(  # type: ignore[attr-defined]
        state, source, tuple(tables), columns
    )
    _load.replica_key_columns = lambda _name: KEY  # type: ignore[attr-defined]
    _load.replica_stamp_column = LANDED_AT  # type: ignore[attr-defined]
    _load.freshness_probe = _freshness_probe  # type: ignore[attr-defined]
    return _load


__all__ = ["SCHEMA", "make_logs_loader", "files_token", "source_settings"]
