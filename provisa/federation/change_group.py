# Copyright (c) 2026 Kenneth Stott
# Canary: 3e98f437-e5b4-4e12-a7a4-86946a4788a7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Changes to several landed tables that belong together.

One read of a source may change several tables at once -- a mailbox's messages, their
recipients, their attachments -- and a reader must not see one table changed and another not.
``EngineRuntime.apply_change_group`` applies a group in the order given, in ONE transaction
where the store has one across tables (PostgreSQL, an embedded DuckDB store, any store written
through one SQLAlchemy connection that honours a transaction). Where it has none, each table's
change is still its own statement and the ORDER is what keeps a reader from a torn row: the
caller puts dependants first and the table readers start from last when adding, and that table
first when removing (:func:`ordered`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TableChanges:
    """The changes to one landed table: rows to add or replace by key (``operation`` insert or
    update), and keys to remove (``operation`` delete), as ``apply_cdc`` takes them."""

    schema: str
    table: str
    columns: list[tuple[str, str]]
    pk_columns: list[str]
    events: list = field(default_factory=list)


@dataclass(frozen=True)
class Change:
    """One row added or replaced by key (``upsert``), or one key removed (``delete``)."""

    operation: str
    row: dict[str, Any]


def ordered(
    changes: dict[str, TableChanges], *, head: str, removed: bool = False
) -> list[TableChanges]:
    """``changes`` (by a name of the caller's) in the order that never shows ``head``'s row
    without its dependants: the others first and ``head`` last when rows are added or
    replaced; ``head`` first when they are removed. Tables with nothing to do are left out."""
    rest = [c for name, c in sorted(changes.items()) if name != head and c.events]
    first = [changes[head]] if head in changes and changes[head].events else []
    return [*first, *rest] if removed else [*rest, *first]
