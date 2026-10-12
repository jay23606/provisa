# Copyright (c) 2026 Kenneth Stott
# Canary: d3645487-b103-408e-95ee-c6709ac29aca
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Cosmos DB container's change feed, as the native change signal follows it (REQ-1982).

The feed is read in its pull model, latest-version mode, from the moment it is opened: each read
returns the documents written since the last, and a continuation carries the place forward. A
deleted document is not in this mode's feed: a table following it sees a deletion at its next
full refresh (the "all versions and deletes" mode, which needs the account's continuous backup,
is not used). The feed answers as the change-stream listener expects a stream to
(``events.push_wiring.follow_changes``): ``try_next`` gives the next change, or None when none
arrived within the wait.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any


class CosmosChangeFeed:
    """The change feed of one container, polled every ``wait_s`` seconds while it is quiet."""

    alive = True

    def __init__(self, container: Any, wait_s: float) -> None:
        self._container = container
        self._wait_s = wait_s
        self._continuation: str | None = None
        self._pending: deque[dict] = deque()

    def _read(self) -> list[dict]:
        if self._continuation is None:
            pages = self._container.query_items_change_feed(start_time="Now")
        else:
            pages = self._container.query_items_change_feed(continuation=self._continuation)
        changes = list(pages)
        self._continuation = self._container.client_connection.last_response_headers["etag"]
        return changes

    async def open(self) -> None:
        """Place the feed at now: a change written from here on is read."""
        await asyncio.to_thread(self._read)

    async def try_next(self) -> dict | None:
        if not self._pending:
            self._pending.extend(await asyncio.to_thread(self._read))
        if self._pending:
            return self._pending.popleft()
        await asyncio.sleep(self._wait_s)
        return None


@asynccontextmanager
async def open_change_feed(
    *, connection: Any, container: str, wait_ms: int
) -> AsyncGenerator[CosmosChangeFeed]:
    """The change feed of ``container``, read from now on."""
    feed = CosmosChangeFeed(connection.container(container), wait_ms / 1000)
    await feed.open()
    yield feed
