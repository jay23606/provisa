# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A PostgreSQL source's own change stream, read from a logical replication slot (REQ-929).

A table of a PostgreSQL source on the ``native`` change signal is kept current by its database's
logical replication: Provisa holds one slot per source and reads, from it, which tables changed.
It reads no rows from the slot; each burst of changes to a table asks for a build of its replica,
as a MongoDB change stream does (REQ-1861). The slot decodes with ``pgoutput``, the plugin built
into every PostgreSQL since 10, read through the SQL interface
(``pg_logical_slot_get_binary_changes``), over a publication of the source's ``native`` tables.
No Kafka is involved.

The database must allow it as it must for Debezium: ``wal_level`` logical, a connecting role
with the replication right (or a superuser) that may create a publication of the tables, and a
primary rather than a read replica. A source that does not is refused by name. The slot and its
publication are created when the first table follows them and dropped when none does any more or
the source is deleted: a slot nobody reads holds the source's WAL.
"""

# Requirements: REQ-929, REQ-1861

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PLUGIN = "pgoutput"
_SLOT_MAX = 63  # PostgreSQL's identifier length
# pgoutput message types that name the relation they change, by their first byte.
_ROW_CHANGES = frozenset(b"IUD")
_TRUNCATE = ord("T")


class LogicalReplicationRefused(ValueError):
    """The source's database cannot give Provisa its change stream."""

    code = "schema.logical_replication_refused"

    def __init__(self, source_id: str, reason: str) -> None:
        self.params = {"source": source_id, "reason": reason}
        super().__init__(
            f"Source {source_id!r}: change_signal 'native' needs the database's logical "
            f"replication, and {reason}"
        )


@dataclass(frozen=True)
class PgConnection:
    """How a PostgreSQL source is reached, its credentials resolved at use."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_source(cls, source: Any) -> "PgConnection":
        from provisa.core.secrets import resolve_secrets

        return cls(
            host=resolve_secrets(source.host or ""),
            port=int(source.port or 5432),
            database=resolve_secrets(source.database or ""),
            user=resolve_secrets(source.username or ""),
            password=resolve_secrets(source.password or ""),
        )

    def connect(self) -> Any:
        import psycopg

        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
            autocommit=True,
        )


def slot_name(source_id: str) -> str:
    """The slot Provisa holds for ``source_id``: lower case letters, digits and underscores."""
    return ("provisa_" + re.sub(r"[^a-z0-9_]", "_", source_id.lower()))[:_SLOT_MAX]


def refusal(conn: Any) -> str | None:
    """Why the connected database cannot give a logical replication slot, or None."""
    wal_level, in_recovery, may_replicate = conn.execute(
        "SELECT current_setting('wal_level'), pg_is_in_recovery(), "
        "(SELECT rolreplication OR rolsuper FROM pg_roles WHERE rolname = current_user)"
    ).fetchone()
    if wal_level != "logical":
        return f"its wal_level is {wal_level!r}, not 'logical'"
    if in_recovery:
        return "it is a read replica (a slot is made on the primary)"
    if not may_replicate:
        return "the source's role has no replication right"
    return None


def require(source: Any) -> None:
    """Refuse ``source`` by name when its database cannot give a logical replication slot."""
    with PgConnection.from_source(source).connect() as conn:
        reason = refusal(conn)
    if reason is not None:
        raise LogicalReplicationRefused(source.id, reason)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ensure_slot(conn: Any, name: str, tables: list[tuple[str, str]]) -> None:
    """Make the publication ``name`` publish exactly ``tables`` and the slot ``name`` decode it,
    creating either that does not exist."""
    listed = ", ".join(f"{_quoted(schema)}.{_quoted(table)}" for schema, table in sorted(tables))
    published = conn.execute("SELECT 1 FROM pg_publication WHERE pubname = %s", (name,)).fetchone()
    if published is None:
        conn.execute(f"CREATE PUBLICATION {_quoted(name)} FOR TABLE {listed}")
    else:
        conn.execute(f"ALTER PUBLICATION {_quoted(name)} SET TABLE {listed}")
    exists = conn.execute(
        "SELECT 1 FROM pg_replication_slots WHERE slot_name = %s", (name,)
    ).fetchone()
    if exists is None:
        conn.execute("SELECT pg_create_logical_replication_slot(%s, %s)", (name, PLUGIN))


def drop_slot(conn: Any, name: str) -> None:
    """Drop the slot ``name`` and its publication, each when it exists."""
    exists = conn.execute(
        "SELECT 1 FROM pg_replication_slots WHERE slot_name = %s", (name,)
    ).fetchone()
    if exists is not None:
        conn.execute("SELECT pg_drop_replication_slot(%s)", (name,))
    conn.execute(f"DROP PUBLICATION IF EXISTS {_quoted(name)}")


def _relids(message: bytes) -> list[int]:
    """The relations one pgoutput message changes: its relation id for a row change, every id it
    names for a truncate, none for any other message (begin, commit, relation, type...)."""
    kind = message[0]
    if kind in _ROW_CHANGES:
        return [int.from_bytes(message[1:5], "big")]
    if kind == _TRUNCATE:
        count = int.from_bytes(message[1:5], "big")
        ids = message[6 : 6 + 4 * count]  # after the count and one byte of options
        return [int.from_bytes(ids[i : i + 4], "big") for i in range(0, len(ids), 4)]
    return []


def read_changes(conn: Any, name: str, limit: int) -> set[tuple[str, str]]:
    """Consume up to ``limit`` messages from the slot and return the (schema, table) pairs they
    changed: what they are is gone from the slot after."""
    rows = conn.execute(
        "SELECT data FROM pg_logical_slot_get_binary_changes(%s, NULL, %s, "
        "'proto_version', '1', 'publication_names', %s)",
        (name, limit, name),
    ).fetchall()
    relids = {relid for row in rows for relid in _relids(bytes(row[0]))}
    if not relids:
        return set()
    named = conn.execute(
        "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.oid = ANY(%s)",
        (sorted(relids),),
    ).fetchall()
    return {(schema, table) for schema, table in named}
