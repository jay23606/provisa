# Copyright (c) 2026 Kenneth Stott
# Canary: fedb0629-21bb-4b6f-9715-0a529f6d7c33
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Where the last completed read of a mail source reached (REQ-1923).

One row for each (source, mailbox, scope, kind):

- ``scope`` is '' for something that is the mailbox's as a whole, or a folder's id;
- ``kind`` is :data:`PROBE` (what the read saw, kept only to ask "changed since?"),
  :data:`DELTA` (where an incremental read continues from), or :data:`GRANT` (the approval a
  mailbox's owner gave at sign-in, which the provider issued and may replace at each renewal);
- ``token`` is the provider's own and opaque here: compared, or handed back to the provider.

Rows are written when the build that read to them is recorded as completed (a source's
``committed``, awaited by the replica runner), never when the read ends: a token is then never
ahead of the copy it describes. Kept in the org's state store, beside ``replica_state``.
"""

# Requirements: REQ-1923
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from provisa.core.schema_org import mail_sync_state

PROBE = "probe"
DELTA = "delta"
#: What a read reached: replaced whole by each completed read (:func:`replace`).
KINDS = frozenset({PROBE, DELTA})
#: The approval a mailbox's owner gave at sign-in (a refresh token the provider issued), kept
#: under the mailbox's own scope. It is sign-in state, not something a read reached: a completed
#: read leaves it alone, and only a sign-in or a renewal writes it (:func:`keep_grant`).
GRANT = "grant"

#: (account, scope, kind): the address of one token of a source.
Key = tuple[str, str, str]


async def read_all(conn: Any, source_id: str) -> dict[Key, str]:
    """Every token kept for ``source_id``."""
    found = await conn.execute_core(
        select(
            mail_sync_state.c.account,
            mail_sync_state.c.scope,
            mail_sync_state.c.kind,
            mail_sync_state.c.token,
        ).where(mail_sync_state.c.source_id == source_id, mail_sync_state.c.kind.in_(KINDS))
    )
    return {(r.account, r.scope, r.kind): r.token for r in found.fetchall()}


async def replace(conn: Any, source_id: str, rows: dict[Key, str]) -> None:
    """Make ``rows`` everything kept for ``source_id``: what a completed read of its mailboxes
    reached, with the mailboxes and folders it no longer saw forgotten. One transaction."""
    unknown = sorted({kind for _a, _s, kind in rows} - KINDS)
    if unknown:
        raise ValueError(f"mail_sync_state: no such kind of token: {', '.join(unknown)}")
    now = datetime.now(UTC)
    async with conn.transaction():
        await conn.execute_core(
            delete(mail_sync_state).where(
                mail_sync_state.c.source_id == source_id, mail_sync_state.c.kind.in_(KINDS)
            )
        )
        for (account, scope, kind), token in rows.items():
            await conn.execute_core(
                mail_sync_state.insert().values(
                    source_id=source_id,
                    account=account,
                    scope=scope,
                    kind=kind,
                    token=token,
                    updated_at=now,
                )
            )


async def forget(conn: Any, source_id: str) -> None:
    """Keep nothing of what a read of ``source_id`` reached: its next read starts from the
    beginning. A mailbox owner's approval is not what a read reached, and stands."""
    await conn.execute_core(
        delete(mail_sync_state).where(
            mail_sync_state.c.source_id == source_id, mail_sync_state.c.kind.in_(KINDS)
        )
    )


def _grant_of(source_id: str, account: str) -> Any:
    return (
        (mail_sync_state.c.source_id == source_id)
        & (mail_sync_state.c.account == account.lower())
        & (mail_sync_state.c.scope == "")
        & (mail_sync_state.c.kind == GRANT)
    )


async def grant(conn: Any, source_id: str, account: str) -> str | None:
    """The approval kept for ``account`` of ``source_id``, or None when its owner has not
    signed in (or the source was connected before approvals were kept here)."""
    found = await conn.execute_core(
        select(mail_sync_state.c.token).where(_grant_of(source_id, account))
    )
    row = found.fetchone()
    return None if row is None else row.token


async def keep_grant(conn: Any, source_id: str, account: str, token: str) -> None:
    """Keep ``token`` as the approval of ``account`` of ``source_id``, in place of any kept
    before: what a sign-in gave, or what the provider answered a renewal with."""
    async with conn.transaction():
        await conn.execute_core(delete(mail_sync_state).where(_grant_of(source_id, account)))
        await conn.execute_core(
            mail_sync_state.insert().values(
                source_id=source_id,
                account=account.lower(),
                scope="",
                kind=GRANT,
                token=token,
                updated_at=datetime.now(UTC),
            )
        )


async def forget_grant(conn: Any, source_id: str, account: str | None = None) -> None:
    """Keep no approval for ``account`` of ``source_id`` (every account's when None)."""
    where = (mail_sync_state.c.source_id == source_id) & (mail_sync_state.c.kind == GRANT)
    if account is not None:
        where = _grant_of(source_id, account)
    await conn.execute_core(delete(mail_sync_state).where(where))


async def granted_at(conn: Any, source_id: str, account: str) -> datetime | None:
    """When the approval kept for ``account`` of ``source_id`` was last written; None when
    none is kept."""
    found = await conn.execute_core(
        select(mail_sync_state.c.updated_at).where(_grant_of(source_id, account))
    )
    row = found.fetchone()
    return None if row is None else row.updated_at
