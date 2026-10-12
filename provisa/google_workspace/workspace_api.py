# Copyright (c) 2026 Kenneth Stott
# Canary: 3b8e1f40-6c2d-4a97-9e15-d07a4c3b2f86
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""One Google account's Calendar and Tasks, as their REST APIs answer it (REQ-1994).

The same posture as :mod:`provisa.google_workspace.gmail`: a rate refusal (429, 403
``rateLimitExceeded`` / ``userRateLimitExceeded``) or a server error is tried again after the
wait Google names, else one that doubles, until the waits of the call would add up to more than
the call may wait; then the call fails with Google's own reason. A scope the account's approval
does not carry is refused as that, naming what to do. Nothing is tried again that trying again
does not change.
"""

# Requirements: REQ-1994
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from provisa.google_workspace.gmail import (
    _FIRST_WAIT,
    _LONGEST_WAIT,
    _RATE_REASONS,
    WAIT_SECONDS,
    GmailNotFound,
    GmailRefused,
    GmailUnavailable,
    QuotaExhausted,
    _asked_wait,
    _reason,
)

CALENDAR_URL = "https://www.googleapis.com/calendar/v3/"
TASKS_URL = "https://tasks.googleapis.com/tasks/v1/"
_TIMEOUT = 30.0
#: What Google answers a call the access token's scopes do not cover.
_SCOPE_REASONS = frozenset({"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"})


class ScopeNotGranted(GmailRefused):
    """The account's approval does not cover the call: it was given before the source asked for
    what it reads now. Its owner signs in again (one mailbox), or the domain's administrator
    adds the scope to the service account's delegation (the organisation's mailboxes)."""

    def __init__(self, account: str, call: str, status: int, reason: str) -> None:
        super().__init__(account, call, status, reason)
        self.args = (
            f"Google refused {call} for {account}: the approval does not cover it ({reason}). "
            "Sign in again from the source's form to grant what the source now reads; for the "
            "organisation's mailboxes, add the source's scopes to the service account's "
            "domain-wide delegation",
        )


class WorkspaceApi:
    """One account's Calendar and Tasks. ``access_token`` answers the token each call is sent
    with."""

    def __init__(
        self,
        account: str,
        access_token: Callable[[], Awaitable[str]],
        client: httpx.AsyncClient,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        quota_user: bool = False,
        wait_seconds: float = WAIT_SECONDS,
    ) -> None:
        self.account = account
        self._token, self._client, self._sleep = access_token, client, sleep
        self._quota_user = quota_user
        self._wait_seconds = wait_seconds

    async def call(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        call: str,
    ) -> dict:
        """Google's answer to one call, or its refusal. An answer with no body (a delete) is
        an empty dict."""
        if self._quota_user:
            params = {**(params or {}), "quotaUser": self.account}
        doubling, waited = _FIRST_WAIT, 0.0
        while True:
            answer = await self._client.request(
                method,
                url,
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {await self._token()}"},
                timeout=_TIMEOUT,
            )
            status = answer.status_code
            if status in (200, 201):
                return answer.json()
            if status == 204:
                return {}
            reason = _reason(answer)
            rate_limited = status == 429 or (status == 403 and reason in _RATE_REASONS)
            if status in (404, 410):
                raise GmailNotFound(self.account, call, status, reason)
            if status == 403 and reason in _SCOPE_REASONS:
                raise ScopeNotGranted(self.account, call, status, reason)
            if status == 403 and reason == "dailyLimitExceeded":
                raise QuotaExhausted(self.account, call, status, reason)
            if not rate_limited and status < 500:
                raise GmailRefused(self.account, call, status, reason)
            wait = _asked_wait(answer)
            if wait is None:
                wait, doubling = doubling, min(doubling * 2, _LONGEST_WAIT)
            if waited + wait > self._wait_seconds:
                refusal = QuotaExhausted if rate_limited else GmailUnavailable
                raise refusal(
                    self.account,
                    call,
                    status,
                    f"{reason}; still refused after waiting {waited:g}s of {self._wait_seconds:g}s",
                )
            await self._sleep(wait)
            waited += wait

    async def pages(self, url: str, params: dict[str, Any], *, call: str) -> AsyncIterator[dict]:
        """Every page of a list call, to the last; each page whole (its items and its own
        fields, such as a calendar's ``updated``)."""
        params = dict(params)
        while True:
            page = await self.call("GET", url, params=params, call=call)
            yield page
            token = page.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    # -- calendar ------------------------------------------------------------------------

    def calendar_url(self, path: str) -> str:
        return CALENDAR_URL + path

    async def calendars(self) -> list[dict]:
        out: list[dict] = []
        async for page in self.pages(
            self.calendar_url("users/me/calendarList"),
            {"maxResults": 250, "showHidden": "true"},
            call="calendarList.list",
        ):
            out.extend(page.get("items", []))
        return out

    async def events(self, calendar_id: str) -> AsyncIterator[list[dict]]:
        """Single events, series masters and exceptions (``singleEvents=false``), with the
        cancelled occurrences of live series (``showDeleted``), a page at a time."""
        async for page in self.pages(
            self.calendar_url(f"calendars/{_quoted(calendar_id)}/events"),
            {"maxResults": 2500, "singleEvents": "false", "showDeleted": "true"},
            call="events.list",
        ):
            yield page.get("items", [])

    async def calendar_updated(self, calendar_id: str) -> str | None:
        """When anything of the calendar last changed (the list's own ``updated``): one call
        of one item."""
        page = await self.call(
            "GET",
            self.calendar_url(f"calendars/{_quoted(calendar_id)}/events"),
            params={"maxResults": 1, "showDeleted": "true", "fields": "updated"},
            call="events.list",
        )
        return page.get("updated")

    # -- tasks ---------------------------------------------------------------------------

    async def task_lists(self) -> list[dict]:
        out: list[dict] = []
        async for page in self.pages(
            TASKS_URL + "users/@me/lists", {"maxResults": 100}, call="tasklists.list"
        ):
            out.extend(page.get("items", []))
        return out

    async def tasks(self, list_id: str) -> AsyncIterator[list[dict]]:
        async for page in self.pages(
            TASKS_URL + f"lists/{_quoted(list_id)}/tasks",
            {
                "maxResults": 100,
                "showCompleted": "true",
                "showHidden": "true",
                "showDeleted": "true",
            },
            call="tasks.list",
        ):
            yield page.get("items", [])


def _quoted(part: str) -> str:
    """An id as one segment of an address: a calendar id is an address, with an ``@``."""
    from urllib.parse import quote

    return quote(part, safe="")
