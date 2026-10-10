# Copyright (c) 2026 Kenneth Stott
# Canary: c80d057b-3794-4a30-9f98-3b557642e4ba
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Reading one mailbox through the Gmail API (REQ-1923).

What is particular to Gmail's API and decided here:

- **A list answers ids only.** ``messages.list`` gives each message's id and thread; the message
  itself is one ``messages.get`` per id.
- **Every call is priced.** Google counts quota units per call (5 for a page of ids, 20 for a
  message) against 6,000 units a minute for each mailbox. :class:`Pacer` holds a mailbox under
  that figure, so a read is slow rather than refused.
- **A refusal is named.** Google's rate refusals (429, and 403 ``rateLimitExceeded`` /
  ``userRateLimitExceeded``) and its server errors are tried again after a wait -- the one
  Google names (``Retry-After``) where it names one, else one that doubles -- until the waits
  of the call would add up to more than the read may wait; then the read fails with Google's
  own reason (:class:`QuotaExhausted`, :class:`GmailUnavailable`). A replica's read may wait
  as long as the operator's setting says (``mail.throttle_wait_seconds``) and says on the
  build's record that it is waiting. The project's daily limit, a domain's
  policy and a refused credential are not tried again. Nothing here answers a partial read as
  if it were whole.

The figures are Google's published ones (developers.google.com/workspace/gmail/api/reference/
quota and .../guides/handle-errors, read 2026-10-09).
"""

# Requirements: REQ-1923
from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from provisa.google_workspace.settings import MAIL_FULL, MailSettings

BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/"

#: Quota units each call costs.
COST: dict[str, int] = {
    "getProfile": 1,
    "labels.list": 1,
    "labels.get": 1,
    "messages.list": 5,
    "messages.get": 20,
}
#: Units a minute Google allows one mailbox, per project.
UNITS_PER_MINUTE = 6000
#: The most ids Google answers in one page.
PAGE_SIZE = 500

_TIMEOUT = 30.0
_FIRST_WAIT = 1.0  # Google: start retries at least one second after the error
_LONGEST_WAIT = 32.0
#: How long the waits of one refused call may add up to before the read fails, where the
#: caller states no bound of its own. A replica's build takes the operator's setting
#: (``mail.throttle_wait_seconds``); this is the bound of a call a person is waiting on.
WAIT_SECONDS = 60.0
_RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


class GmailRefused(Exception):
    """Google refused a call, for a reason that trying again does not change."""

    def __init__(self, account: str, call: str, status: int, reason: str) -> None:
        super().__init__(f"Gmail refused {call} for {account}: {reason} (HTTP {status})")
        self.account, self.call, self.status, self.reason = account, call, status, reason


class QuotaExhausted(GmailRefused):
    """Google's quota did not admit the call: its daily limit, or its rate limit after every
    wait was spent."""


class GmailUnavailable(GmailRefused):
    """Google's servers failed the call each time it was tried."""


class GmailNotFound(GmailRefused):
    """What was asked for does not exist (a message deleted since it was listed)."""


def _asked_wait(answer: httpx.Response) -> float | None:
    """The seconds Google asked the caller to wait (``Retry-After``), or None when it named
    none or named a date."""
    asked = answer.headers.get("Retry-After", "").strip()
    return float(asked) if asked.isdigit() else None


def _out_of_wait(reason: str, waited: float, mailbox: "Gmail") -> str:
    return (
        f"{reason}; the read waited {waited:g}s of the {mailbox._wait_seconds:g}s it may and "
        'was still refused. To wait longer, raise the setting "Longest wait when a mail '
        'service is throttling"; to be throttled less, lower "Mailboxes read at once"'
    )


class Pacer:
    """Holds one mailbox's calls under Google's units a minute: a call waits until the units
    spent in the last minute leave room for it."""

    def __init__(
        self,
        units_per_minute: int = UNITS_PER_MINUTE,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._budget, self._clock, self._sleep = units_per_minute, clock, sleep
        self._spent: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def spend(self, units: int) -> None:
        if units > self._budget:
            raise ValueError(f"a call of {units} units never fits {self._budget} a minute")
        async with self._lock:
            while True:
                now = self._clock()
                while self._spent and self._spent[0][0] <= now - 60.0:
                    self._spent.popleft()
                if sum(u for _, u in self._spent) + units <= self._budget:
                    self._spent.append((now, units))
                    return
                await self._sleep(self._spent[0][0] + 60.0 - now)


def _reason(answer: httpx.Response) -> str:
    """Google's own word for why it refused, or the status when it gave none."""
    try:
        error = answer.json()["error"]
        return str(error["errors"][0]["reason"])
    except (ValueError, KeyError, IndexError, TypeError):
        return f"HTTP {answer.status_code}"


def search_query(mail: MailSettings) -> str | None:
    """What Gmail is asked to search for: the operator's own search, and nothing received before
    the day they named. The day begins at midnight UTC and is given in seconds, which is how
    Google says to state a moment exactly (a date would be read as Pacific time)."""
    terms: list[str] = []
    if mail.search:
        terms.append(mail.search)
    if mail.since is not None:
        midnight = dt.datetime.combine(mail.since, dt.time(), dt.timezone.utc)
        terms.append(f"after:{int(midnight.timestamp())}")
    return " ".join(terms) or None


class Gmail:
    """One mailbox. ``access_token`` answers the token each call is sent with."""

    def __init__(
        self,
        account: str,
        access_token: Callable[[], Awaitable[str]],
        client: httpx.AsyncClient,
        *,
        pacer: Pacer | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        quota_user: bool = False,
        wait_seconds: float = WAIT_SECONDS,
        waiting: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.account = account
        self._token, self._client, self._sleep = access_token, client, sleep
        #: The most the waits of one refused call may add up to.
        self._wait_seconds = wait_seconds
        #: Told how long a call Google is throttling is about to wait, and 0 when it is over.
        self._waiting = waiting
        self._pacer = pacer if pacer is not None else Pacer(sleep=sleep)
        # A service account reading as many users: each call says whose allowance it is
        # counted against (Google's ``quotaUser`` system parameter).
        self._quota_user = quota_user

    async def _call(self, call: str, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{BASE_URL}{self.account}/{path}"
        if self._quota_user:
            params = {**(params or {}), "quotaUser": self.account}
        doubling, waited, throttled = _FIRST_WAIT, 0.0, False
        while True:
            await self._pacer.spend(COST[call])
            answer = await self._client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {await self._token()}"},
                timeout=_TIMEOUT,
            )
            status = answer.status_code
            if status == 200:
                if throttled and self._waiting is not None:
                    await self._waiting(0)
                return answer.json()
            reason = _reason(answer)
            rate_limited = status == 429 or (status == 403 and reason in _RATE_REASONS)
            if status == 404:
                raise GmailNotFound(self.account, call, status, reason)
            if status == 403 and reason == "dailyLimitExceeded":
                raise QuotaExhausted(self.account, call, status, reason)
            if not rate_limited and status < 500:
                raise GmailRefused(self.account, call, status, reason)
            wait = _asked_wait(answer)
            if wait is None:
                wait, doubling = doubling, min(doubling * 2, _LONGEST_WAIT)
            if waited + wait > self._wait_seconds:
                if throttled and self._waiting is not None:
                    await self._waiting(0)
                refusal = QuotaExhausted if rate_limited else GmailUnavailable
                raise refusal(self.account, call, status, _out_of_wait(reason, waited, self))
            if rate_limited and self._waiting is not None:
                throttled = True
                await self._waiting(wait)
            await self._sleep(wait)
            waited += wait

    async def profile(self) -> dict:
        """The mailbox's own address, totals and current history id."""
        return await self._call("getProfile", "profile")

    async def labels(self) -> list[dict]:
        """Every label: id, name and kind. Their counts are one more call each
        (:meth:`label`)."""
        return (await self._call("labels.list", "labels")).get("labels", [])

    async def label(self, label_id: str) -> dict:
        return await self._call("labels.get", f"labels/{label_id}")

    async def label_ids(self, names: tuple[str, ...]) -> list[str]:
        """The ids of the labels the operator named, refusing a name the mailbox does not
        have: a label that is not there would otherwise narrow the read to nothing."""
        if not names:
            return []
        by_name = {label["name"]: label["id"] for label in await self.labels()}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise GmailRefused(
                self.account, "labels.list", 200, f"no label named {', '.join(missing)}"
            )
        return [by_name[name] for name in names]

    async def message_ids(self, mail: MailSettings) -> AsyncIterator[list[str]]:
        """The ids of the mail the source holds, a page at a time, to the last page."""
        params: dict[str, Any] = {"maxResults": PAGE_SIZE}
        label_ids = await self.label_ids(mail.labels)
        if label_ids:
            params["labelIds"] = label_ids
        if mail.include_spam_trash:
            params["includeSpamTrash"] = "true"
        query = search_query(mail)
        if query is not None:
            params["q"] = query
        while True:
            page = await self._call("messages.list", "messages", params)
            ids = [message["id"] for message in page.get("messages", [])]
            if ids:
                yield ids
            token = page.get("nextPageToken")
            if not token:
                return
            params = {**params, "pageToken": token}

    async def message(self, message_id: str, mail: MailSettings) -> dict:
        """One message: whole, or its headers and labels only, as the source reads mail."""
        return await self._call(
            "messages.get",
            f"messages/{message_id}",
            {"format": "full" if mail.content == MAIL_FULL else "metadata"},
        )
