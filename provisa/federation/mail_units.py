# Copyright (c) 2026 Kenneth Stott
# Canary: 6c473a50-8fe7-46d6-873b-16b33fee90a5
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A mail source's replicas, kept in place a unit at a time.

A whole build copies every mailbox into a build table and swaps it in when the last one has
been read: nothing can be queried until then, and a source of many mailboxes takes a long time.
Here each :class:`~provisa.core.canonical_mail.Unit` a reader gives -- a page of a mailbox's
messages with their recipients and attachments, or what changed in a mailbox since it was last
read -- is written to the replicas as it arrives, all its tables together
(``EngineRuntime.apply_change_group``), and can be queried at once.

WHAT IS WRITTEN WHEN. A unit's rows are written first; where its read reached is kept second,
and only then. Writing a unit twice leaves the same rows (rows are replaced by key, removals
name rows that are then not there), so a process that stops between the two reads the same
changes again and nothing is lost or doubled.

ORDER. Every unit is written under the source's turn (``mail_landing.Stamps``): its rows carry
one stamp, later than every stamp before it, and are in the store before a later stamp is
given. The mailboxes are read at the same time; only the writes take turns.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from provisa.core.canonical_mail import LANDED_AT, Unit, key_columns
from provisa.federation.change_group import Change, TableChanges
from provisa.federation.mail_landing import Stamps

#: The table a reader of the mail tables starts from: a row of it is never there without the
#: rows that depend on it, where the store cannot write several tables as one.
HEAD = "messages"

#: How a replica kept in place is built, for its record (``replica_state.build_method``).
METHOD = "apply_units"


@dataclass(frozen=True)
class Part:
    """One table's part: where its replica is, and its columns as the replica holds them."""

    schema: str
    table: str
    columns: list[tuple[str, str]]


class UnitSource(Protocol):
    """A read of a mail source that gives its changes a unit at a time."""

    def units(self) -> AsyncIterator[Unit]: ...

    async def keep(self, account: str, links: dict[str, str]) -> None:
        """Keep where the read of ``account`` reached, now that the rows are written."""

    async def forget(self, account: str) -> None:
        """Keep nothing of where an earlier read of ``account`` reached."""


@dataclass
class Landed:
    """What a pass wrote: rows written and removals asked, by table, and the mailboxes whose
    last unit was written."""

    rows: dict[str, int]
    mailboxes: int = 0
    wrote: bool = False


def _stamped_columns(part: Part) -> bool:
    return any(name == LANDED_AT for name, _ in part.columns)


def changes_of(unit: Unit, parts: dict[str, Part], at: Any) -> list[TableChanges]:
    """``unit`` as changes to the replicas ``parts`` names, in the order that never shows a
    message without its dependants where the store cannot write the tables as one: first what
    is removed, the messages before their dependants; then what is added or replaced, the
    dependants (each set replaced whole) before the messages.

    Rows carry ``at`` as when they landed, where the replica has that column. A table the
    unit names and ``parts`` does not is not replicated, and is left out."""

    def part_changes(name: str, *, rows: bool, removed: bool) -> TableChanges | None:
        part = parts[name]
        events = []
        if rows:
            stamp = _stamped_columns(part)
            for row in unit.rows.get(name, ()):
                events.append(Change("upsert", {**row, LANDED_AT: at} if stamp else dict(row)))
        matches = list(unit.removed.get(name, ())) if removed else []
        changes = TableChanges(
            part.schema, part.table, part.columns, list(key_columns(name)), events, matches
        )
        return None if changes.idle else changes

    names = [name for name in parts if name in unit.rows or name in unit.removed]
    dependants = sorted(name for name in names if name != HEAD)
    ordered: list[TableChanges | None] = []
    if HEAD in names:
        ordered.append(part_changes(HEAD, rows=False, removed=True))
    ordered += [part_changes(name, rows=True, removed=True) for name in dependants]
    if HEAD in names:
        ordered.append(part_changes(HEAD, rows=True, removed=False))
    return [changes for changes in ordered if changes is not None]


class ReplicaUnitJob:
    """One pass over a mail source that keeps its replicas in place. Run it once."""

    def __init__(
        self,
        source: UnitSource,
        parts: dict[str, Part],
        apply: Callable[[list[TableChanges]], Awaitable[None]],
        *,
        stamps: Stamps | None = None,
        first_write: Callable[[], Awaitable[None]] | None = None,
        mailbox_done: Callable[[int], Awaitable[None]] | None = None,
        written: Callable[[Unit], Awaitable[None]] | None = None,
    ) -> None:
        if not parts:
            raise ValueError("a pass needs at least one table")
        self._source = source
        self._parts = parts
        self._apply = apply
        self._stamps = stamps or Stamps()
        self._first_write = first_write
        self._mailbox_done = mailbox_done
        self._written = written

    async def run(self) -> Landed:
        landed = Landed({name: 0 for name in self._parts})
        async for unit in self._source.units():
            async with self._stamps.turn() as at:
                group = changes_of(unit, self._parts, at)
                if group:
                    await self._apply(group)
                # Rows first, the place second: a stop between the two reads these changes
                # again, and writing them again leaves the same rows.
                if unit.forget:
                    await self._source.forget(unit.account)
                if unit.links:
                    await self._source.keep(unit.account, unit.links)
            for name in self._parts:
                landed.rows[name] += len(unit.rows.get(name, ()))
            if group:
                if not landed.wrote and self._first_write is not None:
                    await self._first_write()
                landed.wrote = True
                if self._written is not None:
                    await self._written(unit)
            if unit.last:
                landed.mailboxes += 1
                if self._mailbox_done is not None:
                    await self._mailbox_done(landed.mailboxes)
        return landed
