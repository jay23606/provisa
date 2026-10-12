# Copyright (c) 2026 Kenneth Stott
# Canary: 7c18321c-cb63-45c8-9bcd-6e28059efd01
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Reading Microsoft Graph: one GET, a collection followed page by page, and a batch of GETs.

Graph answers a collection as ``{"value": [...], "@odata.nextLink": "<address of the next
page>"}``; the next page is that address used as it is. A refusal carries
``{"error": {"code", "message"}}``. A throttled call (429, or 503 naming a wait) carries
``Retry-After``; it is waited out as asked while the waits of one call stay within
``wait_seconds``, and past that the read fails by name -- never a shorter answer.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://graph.microsoft.com/v1.0"
#: Ids that stay the same when an item moves to another folder.
IMMUTABLE_IDS = 'IdType="ImmutableId"'
#: Graph takes at most this many requests in one batch.
BATCH_SIZE = 20
#: How long the waits a throttled call is asked for may add up to before the read fails, where
#: the caller states no bound of its own. A replica's build takes the operator's setting
#: (``mail.throttle_wait_seconds``); this is the bound of a call a person is waiting on.
WAIT_SECONDS = 60.0
_TIMEOUT = 30.0


class GraphRefused(RuntimeError):
    """Graph refused a call. ``code`` is Graph's own (``ErrorItemNotFound``, ``MailboxNotEnabledForRESTAPI``)."""

    def __init__(self, status: int, code: str, message: str, path: str) -> None:
        super().__init__(f"Microsoft Graph refused {path}: {status} {code}: {message}")
        self.status = status
        self.code = code


class GraphThrottled(RuntimeError):
    """Graph asked the caller to wait for longer than a read waits."""

    def __init__(self, path: str, asked: str, waited: float, bound: float) -> None:
        super().__init__(
            f"Microsoft Graph is throttling {path} (Retry-After: {asked}); the read waited "
            f"{waited:g}s of the {bound:g}s it may and was still refused. To wait longer, raise "
            'the setting "Longest wait when a mail service is throttling"; to be throttled '
            'less, lower "Mailboxes read at once"'
        )
        self.retry_after = asked


#: What Graph answers (with 404) for an item, or a folder, that is not in the mailbox: the
#: mailbox answered, and says it has no such thing. Never a refusal of the mailbox itself.
FOLDER_NOT_THERE = "ErrorFolderNotFound"
NOT_THERE_CODES = frozenset({"ErrorItemNotFound", FOLDER_NOT_THERE})


def not_there(refused: "GraphRefused") -> bool:
    """Whether ``refused`` says an item or a folder asked for is not in the mailbox."""
    return refused.status == 404 and refused.code in NOT_THERE_CODES


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Mapping[str, str]
    body: Any  # the parsed JSON, or None for an empty answer


#: Sends one request: (method, address, query parameters, headers, JSON body) -> Answer.
Send = Callable[[str, str, Mapping[str, str] | None, Mapping[str, str], Any], Answer]


def http_send(client: httpx.Client) -> Send:
    def send(method, url, params, headers, body) -> Answer:
        reply = client.request(
            method, url, params=params, headers=dict(headers), json=body, timeout=_TIMEOUT
        )
        return Answer(reply.status_code, reply.headers, reply.json() if reply.content else None)

    return send


#: The most requests one app may have in flight for ONE mailbox: "Four concurrent requests",
#: for each app ID and mailbox combination, in Microsoft's "Outlook service limits" (Microsoft
#: Graph throttling limits, learn.microsoft.com/graph/throttling-limits), as read 2026-10-10. It
#: is Microsoft's figure, not a choice of ours, so it is no setting. A JSON batch is sent to
#: Outlook up to four requests at a time, so a batch counts as that many.
MAILBOX_CONCURRENCY = 4


class _MailboxGates:
    """Keeps this process's requests for one mailbox within :data:`MAILBOX_CONCURRENCY`,
    whoever makes them: the read of a mailbox's messages, the separate read of its folders
    and the check for changes each read it on their own, and together passed the limit and
    were throttled. A request waits here for room instead of being sent and refused.

    It counts this process only; another process or node reading the same mailbox is told to
    wait by Graph, which the reader then waits out."""

    def __init__(self) -> None:
        self._room = threading.Condition()
        self._in_flight: dict[str, int] = {}

    @contextmanager
    def of(self, mailbox: str, weight: int = 1) -> Iterator[None]:
        weight = max(1, min(weight, MAILBOX_CONCURRENCY))
        with self._room:
            while self._in_flight.get(mailbox, 0) + weight > MAILBOX_CONCURRENCY:
                self._room.wait()
            self._in_flight[mailbox] = self._in_flight.get(mailbox, 0) + weight
        try:
            yield
        finally:
            with self._room:
                left = self._in_flight[mailbox] - weight
                if left:
                    self._in_flight[mailbox] = left
                else:
                    del self._in_flight[mailbox]
                self._room.notify_all()

    def in_flight(self, mailbox: str) -> int:
        with self._room:
            return self._in_flight.get(mailbox, 0)


MAILBOX_GATES = _MailboxGates()


def _requests_in(url: str, body: Any) -> int:
    """How many requests a call is: a batch is as many as it holds, any other call one."""
    if url.endswith("/$batch") and isinstance(body, dict):
        return len(body.get("requests") or [])
    return 1


def _path(url: str) -> str:
    """The address without its query, which may hold a paging token."""
    return url.split("?", 1)[0].removeprefix(BASE_URL)


def graph_address(link: str) -> str:
    """``link`` as an address under Graph, or a refusal. A link kept from an earlier answer is
    sent with the access token, so it is followed only where it leads back to Graph."""
    if not link.startswith(BASE_URL + "/"):
        raise ValueError("a kept link does not lead to Microsoft Graph; it is not followed")
    return link


class DeltaRound:
    """The pages of one delta round, and the link it ended with: where the next round starts.
    ``link`` is None until the round has been read to its end."""

    def __init__(
        self, graph: "Graph", start: str, params: Mapping[str, str] | None, prefer: tuple[str, ...]
    ) -> None:
        self._graph = graph
        self._start = start
        self._params = params
        self._prefer = prefer
        self.link: str | None = None

    def __iter__(self) -> Iterator[list[dict]]:
        if self._start.startswith("/"):
            url, query = BASE_URL + self._start, self._params
        else:
            # A kept link carries its query already: the options of its first round.
            url, query = graph_address(self._start), None
        while True:
            page = self._graph._call("GET", url, query, self._prefer)
            yield page["value"]
            following = page.get("@odata.nextLink")
            if following is None:
                # A round ends with the link the next one starts from; an answer with neither
                # is not one this reader can continue, and says so by the missing key.
                self.link = page["@odata.deltaLink"]
                return
            url, query = graph_address(following), None


class Graph:
    """Graph as one credential reads it. ``token`` gives the access token for each call."""

    def __init__(
        self,
        send: Send,
        token: Callable[[], str],
        *,
        wait_seconds: float = WAIT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        waiting: Callable[[float], None] | None = None,
    ) -> None:
        self._send = send
        self._token = token
        self._wait_seconds = wait_seconds
        self._sleep = sleep
        #: Told how long a throttled call is about to wait, and 0 when the wait is over.
        self._waiting = waiting
        #: The mailbox this client's requests are for, where it reads one (:meth:`for_mailbox`):
        #: they then wait for room among every request this process has in flight for it.
        self._mailbox: str | None = None

    def for_mailbox(self, mailbox: str) -> "Graph":
        """This client, reading ``mailbox``: every request it makes counts against that
        mailbox's :data:`MAILBOX_CONCURRENCY`. The mailbox is the reader's to say, never read
        from an address: a link Graph gave to continue from is opaque, and need not name the
        mailbox the way the request that earned it did (Microsoft's own examples answer
        ``/mailFolders/{id}`` with ``mailfolders('{id}')``)."""
        bound = copy.copy(self)
        bound._mailbox = mailbox.lower()
        return bound

    def _wait(self, seconds: float) -> None:
        """Wait out what Graph asked for, saying so to whoever watches the read."""
        if self._waiting is not None:
            self._waiting(seconds)
        try:
            self._sleep(seconds)
        finally:
            if self._waiting is not None:
                self._waiting(0.0)

    def _call(
        self,
        method: str,
        url: str,
        params: Mapping[str, str] | None,
        prefer: tuple[str, ...],
        body: Any = None,
        also: Mapping[str, str] | None = None,
    ) -> Any:
        waited = 0.0
        while True:
            headers = {**(also or {}), "Authorization": f"Bearer {self._token()}"}
            if prefer:
                headers["Prefer"] = ", ".join(prefer)
            if self._mailbox is None:  # the directory: for no one mailbox
                answer = self._send(method, url, params, headers, body)
            else:
                # Room is held only while the request is in flight, never across a wait.
                with MAILBOX_GATES.of(self._mailbox, _requests_in(url, body)):
                    answer = self._send(method, url, params, headers, body)
            asked = answer.headers.get("Retry-After")
            if answer.status == 429 or (answer.status == 503 and asked is not None):
                if asked is None or not asked.strip().isdigit():
                    raise GraphThrottled(_path(url), str(asked), waited, self._wait_seconds)
                wait = float(asked)
                if waited + wait > self._wait_seconds:
                    raise GraphThrottled(_path(url), asked, waited, self._wait_seconds)
                self._wait(wait)
                waited += wait
                continue
            if answer.status >= 400:
                error = (answer.body or {}).get("error") or {}
                raise GraphRefused(
                    answer.status,
                    str(error.get("code")),
                    str(error.get("message")),
                    _path(url),
                )
            return answer.body

    def get(self, path: str, params: Mapping[str, str] | None = None, *, prefer=()) -> dict:
        return self._call("GET", BASE_URL + path, params, tuple(prefer))

    def write(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: Mapping[str, str] | None = None,
        *,
        prefer=(),
    ) -> Any:
        """A POST, PATCH or DELETE (REQ-1994): Graph's answer, None for an empty one."""
        return self._call(method, BASE_URL + path, params, tuple(prefer), body=body)

    def find(self, path: str, params: Mapping[str, str] | None = None) -> dict | None:
        """One item, or None where Graph says there is no such item."""
        try:
            return self.get(path, params)
        except GraphRefused as refused:
            if not_there(refused):
                return None
            raise

    def pages(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        *,
        prefer=(),
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[list[dict]]:
        """A collection, one page of items at a time, to its end. ``headers`` are sent with
        every page (a directory query that needs ``ConsistencyLevel``)."""
        url, query = BASE_URL + path, params
        while url is not None:
            page = self._call("GET", url, query, tuple(prefer), also=headers)
            yield page["value"]
            # The next page is the address Graph gave, whole: it carries the query already.
            url, query = page.get("@odata.nextLink"), None

    def delta(
        self, start: str, params: Mapping[str, str] | None = None, *, prefer=()
    ) -> "DeltaRound":
        """One round of change tracking over a collection (Graph's delta query). ``start`` is
        the collection's delta path, for a first round that gives everything in it, or the
        link the last round ended with, for what changed since. Iterate it to its end, then
        read its ``link``."""
        return DeltaRound(self, start, params, tuple(prefer))

    def batch(self, paths: list[str], *, prefer=()) -> list[dict]:
        """The answers to GETs of ``paths``, in their order. A refusal of any one fails all."""
        answers = self.batch_each(paths, prefer=prefer)
        for answer in answers:
            if isinstance(answer, GraphRefused):
                raise answer
        return answers  # type: ignore[return-value]  # no refusal is left in it

    def batch_each(self, paths: list[str], *, prefer=()) -> "list[dict | GraphRefused]":
        """The answer to a GET of each of ``paths``, in their order: its body, or the refusal
        Graph gave that one. A throttled request is asked again; throttling past the bound
        fails the whole call."""
        answers: list[dict | GraphRefused] = []
        for start in range(0, len(paths), BATCH_SIZE):
            chunk = paths[start : start + BATCH_SIZE]
            headers = {"Prefer": ", ".join(prefer)} if prefer else {}
            requests = [
                {"id": str(n), "method": "GET", "url": path, "headers": headers}
                if headers
                else {"id": str(n), "method": "GET", "url": path}
                for n, path in enumerate(chunk)
            ]
            pending = {r["id"]: r for r in requests}
            got: dict[str, dict | GraphRefused] = {}
            waited = 0.0
            while pending:
                reply = self._call(
                    "POST", BASE_URL + "/$batch", None, (), {"requests": list(pending.values())}
                )
                wait = 0.0
                for item in reply["responses"]:
                    path = pending[item["id"]]["url"]
                    if item["status"] == 429:
                        asked = (item.get("headers") or {}).get("Retry-After")
                        if asked is None or not str(asked).strip().isdigit():
                            raise GraphThrottled(path, str(asked), waited, self._wait_seconds)
                        wait = max(wait, float(asked))
                        continue
                    if item["status"] >= 400:
                        error = (item.get("body") or {}).get("error") or {}
                        got[item["id"]] = GraphRefused(
                            item["status"],
                            str(error.get("code")),
                            str(error.get("message")),
                            path.split("?", 1)[0],
                        )
                    else:
                        got[item["id"]] = item["body"]
                    del pending[item["id"]]
                if pending:
                    if waited + wait > self._wait_seconds:
                        first = next(iter(pending.values()))["url"]
                        raise GraphThrottled(
                            first.split("?", 1)[0], f"{wait:g}", waited, self._wait_seconds
                        )
                    self._wait(wait)
                    waited += wait
            answers += [got[str(n)] for n in range(len(chunk))]
        return answers
