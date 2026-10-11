# Copyright (c) 2026 Kenneth Stott
# Canary: f3b254ad-526f-4695-a8db-0cb38152ad6f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""How a mail source's rows are stamped as they land.

Every row a landing writes together carries one stamp in ``landed_at``
(``core.canonical_mail.LANDED_AT``), and each stamp of a source is later than the one before
it. Live delivery asks a table for rows whose watermark is greater than the last one it sent,
so a row that lands later must never carry an earlier value than one already sent: the
provider's own ``updated_at`` cannot promise that, a stamp given in the order rows are written
can.

The order is kept by :class:`Stamps`: a stamp is taken and its rows are written while the
source's turn is held, so rows stamped earlier are never written after rows stamped later.
The reads that produce the rows are not in the turn and stay concurrent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

_STEP = timedelta(microseconds=1)


class Stamps:
    """The stamps of one source's landings in one pass, each later than the last."""

    def __init__(self, after: datetime | None = None) -> None:
        self._last = after
        self._turn = asyncio.Lock()

    def _next(self) -> datetime:
        now = datetime.now(UTC)
        if self._last is not None and now <= self._last:
            now = self._last + _STEP
        self._last = now
        return now

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[datetime]:
        """The stamp for what is written inside the block. One block runs at a time, so what
        is stamped earlier has been written before anything is stamped later."""
        async with self._turn:
            yield self._next()
