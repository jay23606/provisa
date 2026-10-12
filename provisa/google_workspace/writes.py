# Copyright (c) 2026 Kenneth Stott
# Canary: 2a6f8d31-5e0b-4c27-8d94-b1c7e3a0f562
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The write driver of a Google Workspace source (REQ-1994): ``federation.mail_write`` with
the Calendar and Tasks writer of each account, signed in as the source's reads are."""

# Requirements: REQ-1994
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from provisa.core import canonical_mail as cm
from provisa.federation.mail_write import MailWriteDriver
from provisa.google_workspace.calendar_write import GoogleWriter
from provisa.google_workspace.gmail import WAIT_SECONDS
from provisa.google_workspace.loader import make_connect, source_settings
from provisa.google_workspace.workspace_api import WorkspaceApi


def write_driver(state: Any, current: Callable[[], Awaitable[Any]]) -> MailWriteDriver:
    """``current`` answers the source as it stands now."""
    connect = make_connect(state)

    async def accounts() -> tuple[str, ...]:
        return (await connect(await current())).accounts

    @asynccontextmanager
    async def writer_for(account: str) -> AsyncIterator[GoogleWriter]:
        source = await current()
        reading = await connect(source)

        async def token() -> str:
            return await reading.token(account)

        async with httpx.AsyncClient() as client:
            api = WorkspaceApi(
                account,
                token,
                client,
                quota_user=reading.organisation,
                # A person is waiting on the write: the bound of a call one waits on.
                wait_seconds=WAIT_SECONDS,
            )
            yield GoogleWriter(api, source_settings(source).send_updates)

    return MailWriteDriver(cm.GOOGLE, accounts, writer_for)
