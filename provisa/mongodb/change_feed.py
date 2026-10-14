# Copyright (c) 2026 Kenneth Stott
# Canary: 4261bc19-6c88-4157-8d62-e65c7c20394c
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Whether a table may follow its source's change feed (REQ-1861, REQ-1982, REQ-929).

A table opts in with the ``native`` change signal (its own, else its source's). MongoDB change
streams are served only by a replica set or a sharded cluster, so a table that opts in on a
standalone server is refused by name, at save and at load, instead of being built once and never
refreshed. A PostgreSQL source's feed is its logical replication, refused by name where its
database does not allow it (``subscriptions.pg_logical``).
"""

# Requirements: REQ-1861

from __future__ import annotations

import asyncio
from typing import Any

from provisa.mongodb.fetch import ChangeStreamsUnavailable, MongoConnection, require_change_streams
from provisa.subscriptions.pg_logical import LogicalReplicationRefused

__all__ = [
    "FEED_REFUSALS",
    "ChangeStreamsUnavailable",
    "follows_change_feed",
    "require_change_feed",
]

#: The change signal that opts a table into its source's change feed (REQ-929).
CHANGE_FEED_SIGNAL = "native"
#: The source types whose own change feed a ``native`` table follows.
CHANGE_FEED_TYPES = frozenset({"mongodb", "cosmosdb", "postgresql"})


#: What :func:`require_change_feed` raises when a source cannot give its feed: each carries the
#: ``code`` and ``params`` it is refused with.
FEED_REFUSALS = (ChangeStreamsUnavailable, LogicalReplicationRefused)


def follows_change_feed(
    source_type: str, table_signal: str | None, source_signal: str | None
) -> bool:
    """Whether a table of a ``source_type`` source follows the source's change feed: a MongoDB
    (REQ-1861) or Cosmos DB (REQ-1982) table whose effective change signal (its own, else its
    source's) is ``native``."""
    signal = table_signal if table_signal is not None else source_signal
    return source_type in CHANGE_FEED_TYPES and signal == CHANGE_FEED_SIGNAL


async def require_change_feed(source: Any) -> None:
    """Refuse a source whose server serves no change streams (:class:`ChangeStreamsUnavailable`).
    The source's connection values are resolved here, at use; a server that cannot be reached
    raises the driver's own error. A Cosmos DB container always serves its change feed
    (REQ-1982): nothing is asked."""
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
    if source_type == "cosmosdb":
        return
    if source_type == "postgresql":
        from provisa.subscriptions import pg_logical

        await asyncio.to_thread(pg_logical.require, source)
        return
    conn = MongoConnection.from_source(source)
    await asyncio.to_thread(require_change_streams, conn, source.id)
