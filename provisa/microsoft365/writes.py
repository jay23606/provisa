# Copyright (c) 2026 Kenneth Stott
# Canary: 1d8c5e27-7b3a-4e91-9f60-a4c2d8e5b713
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The write driver of a Microsoft 365 source (REQ-1994): ``federation.mail_write`` with the
Graph writer of each mailbox, signed in as the source's reads are."""

# Requirements: REQ-1994
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from provisa.core import canonical_mail as cm
from provisa.federation.mail_write import MailWriteDriver
from provisa.microsoft365 import settings as m365
from provisa.microsoft365.calendar_write import GraphWriter
from provisa.microsoft365.graph import WAIT_SECONDS, Graph, http_send
from provisa.microsoft365.loader import make_connect


def write_driver(state: Any, current: Callable[[], Awaitable[Any]]) -> MailWriteDriver:
    """``current`` answers the source as it stands now."""
    connect = make_connect(state)

    async def accounts() -> tuple[str, ...]:
        return (await connect(await current())).accounts

    @asynccontextmanager
    async def writer_for(account: str) -> AsyncIterator[GraphWriter]:
        source = await current()
        reading = await connect(source)
        settings = m365.parse(dict(getattr(source, "mapping", None) or {}))
        with httpx.Client() as client:
            # A person is waiting on the write: the bound of a call one waits on.
            graph = Graph(http_send(client), reading.token, wait_seconds=WAIT_SECONDS)
            yield GraphWriter(graph.for_mailbox(account), account, settings.send_updates)

    return MailWriteDriver(cm.MICROSOFT, accounts, writer_for)
