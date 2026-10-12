# Copyright (c) 2026 Kenneth Stott
# Canary: a16da046-3431-4318-a8b8-ef65b5ab8d3d
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Microsoft 365 mailbox as the canonical mail tables (``provisa.core.canonical_mail``).

Each table is read whole. A row holds every column of its canonical table, in its order; a
column Microsoft has no value for is None. Every enumeration value passes through the shared
translator, so a value Graph answers that its table does not list fails the read by name.

What Graph gives and how it is asked:

- messages are listed once with their bodies as text (``Prefer: outlook.body-content-type``);
  the HTML body is a second read of each page's messages, batched;
- a folder's role comes from Graph's well-known folder names, each asked for by name, since a
  v1.0 folder does not carry it; ``/mailFolders`` answers one level, so the tree is walked;
- attachments are listed for the messages Graph marks as having them (``hasAttachments``,
  which does not count inline ones), without their content.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from provisa.core import canonical_mail as cm
from provisa.microsoft365.graph import (
    BASE_URL,
    IMMUTABLE_IDS,
    Graph,
    GraphRefused,
    graph_address,
    not_there,
)

log = logging.getLogger(__name__)

PROVIDER = cm.MICROSOFT
#: The six mail tables, in the order a registrar is offered them.
MAIL_TABLES = (
    "messages",
    "message_recipients",
    "folders",
    "message_folders",
    "threads",
    "attachments",
)
#: Microsoft's own names for the folders Outlook makes, whatever the mailbox's language calls
#: them: the "Well-known folder names" table of the mailFolder resource type (Microsoft Graph
#: v1.0, learn.microsoft.com/graph/api/resources/mailfolder), all seventeen, as checked against
#: that page on 2026-10-10. A folder's role is told only by asking for it under one of these
#: names: v1.0's mailFolder has no property that says it, so a listing cannot. A mailbox has
#: only some of them.
WELL_KNOWN_FOLDERS = (
    "archive",
    "clutter",
    "conflicts",
    "conversationhistory",
    "deleteditems",
    "drafts",
    "inbox",
    "junkemail",
    "localfailures",
    "msgfolderroot",
    "outbox",
    "recoverableitemsdeletions",
    "scheduled",
    "searchfolders",
    "sentitems",
    "serverfailures",
    "syncissues",
)
PAGE_SIZE = 50
#: The scope of what is kept for the mailbox as a whole (its list of folders), where a
#: folder's own is kept under the folder's id.
MAILBOX = ""
_FOLDER_PAGE = 100
_TEXT_BODY = 'outlook.body-content-type="text"'
_HTML_BODY = 'outlook.body-content-type="html"'
_MESSAGE_FIELDS = (
    "id,conversationId,conversationIndex,internetMessageId,subject,bodyPreview,from,sender,"
    "toRecipients,ccRecipients,bccRecipients,replyTo,sentDateTime,receivedDateTime,"
    "createdDateTime,lastModifiedDateTime,isRead,isDraft,flag,importance,hasAttachments,"
    "parentFolderId,categories,inferenceClassification,isReadReceiptRequested,"
    "isDeliveryReceiptRequested,body,internetMessageHeaders,changeKey,webLink"
)
#: What a folder's change tracking is asked for where the source holds nothing received
#: before a date: only what says whether a message is held. A source with a date usually
#: holds a small part of a mailbox, and the full fields of a message (its text and its
#: headers among them) are then asked for only for the messages held, in batches, as their
#: HTML bodies already are -- so reading past years of old mail costs a line a message, not
#: the message. ``id`` is always returned. Without a date every message is held, and asking
#: for the fields with the listing is the cheaper way.
_DATED_FIELDS = "id,receivedDateTime"
_ATTACHMENT_FIELDS = "id,name,contentType,size,isInline,lastModifiedDateTime"
_RECIPIENT_LISTS = (
    ("to", "toRecipients"),
    ("cc", "ccRecipients"),
    ("bcc", "bccRecipients"),
    ("reply_to", "replyTo"),
)


#: The tables that come from the messages of a mailbox: one read of it gives them all.
MESSAGE_TABLES = (
    "messages",
    "message_recipients",
    "message_folders",
    "threads",
    "attachments",
)
# What a message is asked for when its own row is not wanted: what the other tables read.
_OTHER_FIELDS = (
    "id,conversationId,subject,bodyPreview,receivedDateTime,from,sender,toRecipients,"
    "ccRecipients,bccRecipients,replyTo,parentFolderId,hasAttachments"
)


class UnexpectedAnswer(RuntimeError):
    """Graph answered in a form the reader did not ask for."""


def _row(table: str, account: str, **values: Any) -> dict[str, Any]:
    """A row of ``table``: every canonical column in order, None where no value is given. A
    value for a column the table does not have, or one Microsoft does not populate, is an
    error of this module, raised here."""
    columns = cm.TABLES[table].columns
    known = {c.name: c for c in columns}
    for name in values:
        if name not in known:
            raise KeyError(f"{table} has no column {name!r}")
        if not known[name].populated_by(PROVIDER):
            raise KeyError(f"{table}.{name} is not a column Microsoft populates")
    row: dict[str, Any] = {c.name: values.get(c.name) for c in columns}
    row["provider"] = PROVIDER
    row["account"] = account
    return row


def _address(recipient: dict | None) -> tuple[str | None, str | None]:
    email = (recipient or {}).get("emailAddress") or {}
    return email.get("address"), email.get("name")


def _addresses(recipients: list[dict] | None) -> list[str]:
    return [a for a, _ in map(_address, recipients or []) if a]


def _utc(moment: dict | None) -> str | None:
    """A Graph ``dateTimeTimeZone`` as an ISO-8601 instant. Graph answers these in UTC unless
    asked otherwise, and this reader never asks otherwise."""
    if moment is None:
        return None
    if moment["timeZone"] != "UTC":
        raise UnexpectedAnswer(
            f"Graph answered a time in the zone {moment['timeZone']!r}; UTC was expected"
        )
    stamp = moment["dateTime"]
    whole, dot, fraction = stamp.partition(".")
    return f"{whole}{dot}{fraction[:6]}+00:00"  # Graph writes seven digits of a second


def _header(headers: list[dict], name: str) -> str | None:
    wanted = name.lower()
    return next((h["value"] for h in headers if h["name"].lower() == wanted), None)


def message_row(account: str, item: dict, html: str | None) -> dict[str, Any]:
    body = item["body"]
    if body["contentType"] != "text":
        raise UnexpectedAnswer(
            f"Graph answered the body of a message as {body['contentType']!r}; text was asked for"
        )
    from_address, from_name = _address(item.get("from"))
    headers = item.get("internetMessageHeaders") or []
    references = _header(headers, "References")
    flag = item["flag"]
    status = cm.translate("flag_status", PROVIDER, flag["flagStatus"])
    return _row(
        "messages",
        account,
        id=item["id"],
        thread_id=item["conversationId"],
        internet_message_id=item.get("internetMessageId"),
        in_reply_to=_header(headers, "In-Reply-To"),
        reference_ids=None if references is None else references.split(),
        subject=item.get("subject"),
        snippet=item.get("bodyPreview"),
        from_address=from_address,
        from_name=from_name,
        sender_address=_address(item.get("sender"))[0],
        to_addresses=_addresses(item.get("toRecipients")),
        cc_addresses=_addresses(item.get("ccRecipients")),
        bcc_addresses=_addresses(item.get("bccRecipients")),
        reply_to_addresses=_addresses(item.get("replyTo")),
        sent_at=item.get("sentDateTime"),
        received_at=item.get("receivedDateTime"),
        created_at=item.get("createdDateTime"),
        updated_at=item.get("lastModifiedDateTime"),
        is_read=item["isRead"],
        is_draft=item["isDraft"],
        is_flagged=status == "flagged",
        flag_status=status,
        importance=cm.translate("importance", PROVIDER, item["importance"]),
        has_attachments=item["hasAttachments"],
        folder_ids=[item["parentFolderId"]],
        categories=item.get("categories") or [],
        inference_classification=cm.translate(
            "inference_classification", PROVIDER, item.get("inferenceClassification")
        ),
        is_read_receipt_requested=item.get("isReadReceiptRequested"),
        is_delivery_receipt_requested=item.get("isDeliveryReceiptRequested"),
        body_text=body["content"],
        body_html=html,
        headers=[{"name": h["name"], "value": h["value"]} for h in headers],
        change_key=item.get("changeKey"),
        web_link=item.get("webLink"),
        conversation_index=item.get("conversationIndex"),
        flag_start_at=_utc(flag.get("startDateTime")),
        flag_due_at=_utc(flag.get("dueDateTime")),
        flag_completed_at=_utc(flag.get("completedDateTime")),
    )


def recipient_rows(account: str, item: dict) -> list[dict[str, Any]]:
    people: list[tuple[str, list[dict]]] = [
        ("from", [item["from"]] if item.get("from") else []),
        ("sender", [item["sender"]] if item.get("sender") else []),
    ]
    people += [(kind, item.get(field) or []) for kind, field in _RECIPIENT_LISTS]
    rows = []
    for kind, recipients in people:
        for position, recipient in enumerate(recipients, 1):
            address, name = _address(recipient)
            rows.append(
                _row(
                    "message_recipients",
                    account,
                    message_id=item["id"],
                    kind=cm.canonical("recipient_kind", kind),
                    position=position,
                    address=address,
                    name=name,
                )
            )
    return rows


def message_folder_row(account: str, item: dict) -> dict[str, Any]:
    return _row("message_folders", account, message_id=item["id"], folder_id=item["parentFolderId"])


def folder_row(account: str, item: dict, well_known: str | None) -> dict[str, Any]:
    role = cm.translate("folder_role", PROVIDER, well_known)
    return _row(
        "folders",
        account,
        id=item["id"],
        name=item["displayName"],
        parent_id=item.get("parentFolderId"),
        kind=cm.canonical("folder_kind", "user" if role is None else "system"),
        role=role,
        is_hidden=item.get("isHidden"),
        total_count=item.get("totalItemCount"),
        unread_count=item.get("unreadItemCount"),
        child_count=item.get("childFolderCount"),
    )


def attachment_row(account: str, message_id: str, item: dict) -> dict[str, Any]:
    return _row(
        "attachments",
        account,
        message_id=message_id,
        id=item["id"],
        name=item.get("name"),
        content_type=item.get("contentType"),
        size_bytes=item.get("size"),
        is_inline=item.get("isInline"),
        content_id=item.get("contentId"),
        kind=cm.translate("attachment_kind", PROVIDER, item["@odata.type"]),
        updated_at=item.get("lastModifiedDateTime"),
    )


def thread_rows(account: str, items: list[dict]) -> list[dict[str, Any]]:
    """The threads of ``items`` (messages): one row for each conversation among them."""
    threads: dict[str, list[dict]] = {}
    for item in items:
        threads.setdefault(item["conversationId"], []).append(item)
    rows = []
    for thread_id, messages in threads.items():
        messages.sort(key=lambda m: (m["receivedDateTime"], m["id"]))
        first, last = messages[0], messages[-1]
        rows.append(
            _row(
                "threads",
                account,
                id=thread_id,
                subject=first.get("subject"),
                snippet=last.get("bodyPreview"),
                first_message_at=first["receivedDateTime"],
                last_message_at=last["receivedDateTime"],
                message_count=len(messages),
            )
        )
    return rows


#: What a thread row is worked out from, of each of its messages.
_THREAD_FIELDS = ("id", "conversationId", "subject", "bodyPreview", "receivedDateTime")
#: A kept link Graph no longer honours: the mailbox is read again from its start.
_LINK_GONE_STATUS = 410
_LINK_GONE_CODES = frozenset({"SyncStateNotFound", "syncStateNotFound", "resyncRequired"})


Unit = cm.Unit


def _link_gone(refused: GraphRefused) -> bool:
    return refused.status == _LINK_GONE_STATUS or refused.code in _LINK_GONE_CODES


def _nothing_since(answer: Any) -> bool:
    """Whether a followed link's answer says nothing changed: no item, and the round ended."""
    return (
        isinstance(answer, dict)
        and answer.get("value") == []
        and isinstance(answer.get("@odata.deltaLink"), str)
    )


class Mailbox:
    """One account's mail, read through Graph."""

    def __init__(
        self,
        graph: Graph,
        account: str,
        *,
        page_size: int = PAGE_SIZE,
        since: dt.date | None = None,
    ) -> None:
        # Every request of this mailbox's reader counts against the mailbox, whatever its
        # address looks like (Graph's four concurrent requests for an app and a mailbox).
        self._graph = graph.for_mailbox(account)
        self.account = account.lower()
        self._root = f"/users/{quote(account, safe='@')}"
        self._page_size = page_size
        #: Nothing received before this date is held; None: mail of any age. Graph's change
        #: tracking of a folder takes a filter on the received time but then "returns only up
        #: to 5,000 messages" (Microsoft Graph, "Get incremental changes to messages in a
        #: folder"), which would cut a folder short without saying so. So every message is
        #: asked for and the older ones are left out here.
        self._not_before = None if since is None else since.isoformat()
        #: Where the last whole read of the messages reached: a link for each folder, by its
        #: id, and one for the list of folders (:data:`MAILBOX`). None until such a read ends.
        self.links: dict[str, str] | None = None

    @property
    def graph(self) -> Graph:
        """Graph as this mailbox's reader asks it (REQ-1994: its calendars and tasks too)."""
        return self._graph

    def _held(self, message: dict) -> bool:
        """Whether ``message`` is one this source holds: received on or after its date. A
        message Graph gives no received time for was not received before anything."""
        received = message.get("receivedDateTime")
        return self._not_before is None or received is None or received[:10] >= self._not_before

    def _taken(self, items: list[dict], fields: str, prefer: tuple[str, ...]) -> list[dict]:
        """The messages of ``items`` this source holds, with ``fields``. Where the source has
        a date, ``items`` carry only what says whether each is held (:data:`_DATED_FIELDS`)
        and the fields of the held ones are asked for here, in batches; one removed since it
        was listed is no longer there to hold."""
        held = [m for m in items if self._held(m)]
        if self._not_before is None or not held:
            return held
        answers = self._graph.batch_each(
            [f"{self._root}/messages/{quote(m['id'], safe='')}?$select={fields}" for m in held],
            prefer=(IMMUTABLE_IDS, *prefer),
        )
        taken = []
        for answer in answers:
            if isinstance(answer, GraphRefused):
                if not_there(answer):
                    continue
                raise answer
            taken.append(answer)
        return taken

    def _messages(self, fields: str, *, prefer: tuple[str, ...]) -> Iterator[list[dict]]:
        """Every message of the mailbox, a page at a time, read folder by folder as the first
        round of Graph's change tracking: a first round gives everything in the folder and
        ends with the link from which the next asks only what changed. The links are kept in
        :attr:`links` once every folder has been read to its end.

        Graph tracks changes one folder at a time, so a message is seen where its folder is
        listed: the walk of the folders covers the hidden ones. A message met a second time
        (moved between two folders while they were read) is given once."""
        self.links = None
        links: dict[str, str] = {}
        seen: set[str] = set()
        size = f"odata.maxpagesize={self._page_size}"
        for folder in [f["id"] for page in self._folders() for f in page]:
            changes = self._graph.delta(
                f"{self._root}/mailFolders/{quote(folder, safe='')}/messages/delta",
                {"$select": fields if self._not_before is None else _DATED_FIELDS},
                prefer=(IMMUTABLE_IDS, size, *prefer),
            )
            try:
                for page in changes:
                    # A first round has no removals; one replayed into it is not a message.
                    listed = [m for m in page if "@removed" not in m and m["id"] not in seen]
                    seen.update(m["id"] for m in listed)
                    fresh = self._taken(listed, fields, prefer)
                    if fresh:
                        yield fresh
            except GraphRefused as refused:
                if not not_there(refused):
                    raise
                # The folder was removed after the folders were listed: its messages are no
                # longer there to read. It keeps no link, and the others are read.
                log.info(
                    "microsoft_365 %s: folder %s is no longer there; skipped", self.account, folder
                )
                continue
            assert changes.link is not None  # the round was read to its end
            links[folder] = changes.link
        # The list of folders has a link of its own: a folder made, renamed or removed since.
        listed = self._graph.delta(
            f"{self._root}/mailFolders/delta", {"$select": "id"}, prefer=(IMMUTABLE_IDS,)
        )
        for _page in listed:
            pass
        assert listed.link is not None
        links[MAILBOX] = listed.link
        self.links = links

    def readable(self) -> bool:
        """Whether Graph lets the mailbox be read at all now: one small request."""
        try:
            self._graph.get(f"{self._root}/mailFolders", {"$select": "id", "$top": "1"})
        except GraphRefused:
            return False
        return True

    def changed(self, links: dict[str, str]) -> bool:
        """Whether anything of the mailbox's mail changed since ``links`` were kept: a message
        made, changed, removed or moved in any folder, or the list of folders itself. Each
        link is followed asking for one item; nothing is kept from the answers, so the links
        stand as they were.

        A link says "unchanged" in exactly one way: its answer holds no item AND ends the round
        (an ``@odata.deltaLink``). Graph may give an empty page that is not the last ("there
        are more pages of data to retrieve in the session, even if the current response
        contains an empty result"), so an empty page with more to come is a change. So is a
        link Graph no longer honours, and any answer that is not of that shape."""
        paths = [
            graph_address(link).removeprefix(BASE_URL) for _scope, link in sorted(links.items())
        ]
        if not paths:
            return True  # nothing kept to ask from
        answers = self._graph.batch_each(paths, prefer=("odata.maxpagesize=1",))
        return not all(_nothing_since(answer) for answer in answers)

    def _html(self, page: list[dict], unread: list[str]) -> dict[str, str | None]:
        """The HTML body of each message of ``page``. One Graph will not give is None, and its
        message's id is added to ``unread``: the row is kept without it."""
        answers = self._graph.batch_each(
            [f"{self._root}/messages/{quote(m['id'], safe='')}?$select=body" for m in page],
            prefer=(IMMUTABLE_IDS, _HTML_BODY),
        )
        bodies: dict[str, str | None] = {}
        for message, answer in zip(page, answers):
            if isinstance(answer, GraphRefused):
                bodies[message["id"]] = None
                unread.append(message["id"])
                continue
            body = answer["body"]
            if body["contentType"] != "html":
                raise UnexpectedAnswer(
                    f"Graph answered the body of a message as {body['contentType']!r}; "
                    "html was asked for"
                )
            bodies[message["id"]] = body["content"]
        return bodies

    def _well_known(self) -> dict[str, str]:
        """Folder id -> the well-known name Graph knows it by, for those this mailbox has.
        Asked in one batch. Which of the names a mailbox has depends on the mailbox: one it
        lacks answers that there is no such folder, and has no role to give."""
        answers = self._graph.batch_each(
            [f"{self._root}/mailFolders/{name}?$select=id" for name in WELL_KNOWN_FOLDERS]
        )
        known = {}
        for name, answer in zip(WELL_KNOWN_FOLDERS, answers):
            if isinstance(answer, GraphRefused):
                if not_there(answer):
                    continue
                raise answer
            known[answer["id"]] = name
        return known

    def _folders(self) -> Iterator[list[dict]]:
        query = {"includeHiddenFolders": "true", "$top": str(_FOLDER_PAGE)}
        waiting = [f"{self._root}/mailFolders"]
        while waiting:
            for page in self._graph.pages(waiting.pop(), query):
                yield page
                waiting += [
                    f"{self._root}/mailFolders/{quote(f['id'], safe='')}/childFolders"
                    for f in page
                    if f.get("childFolderCount")
                ]

    def message_tables(
        self, tables: tuple[str, ...] | list[str], unreadable: list[str] | None = None
    ) -> Iterator[tuple[str, list[dict[str, Any]]]]:
        """The rows of several of the tables that come from messages, from ONE listing of the
        mailbox: each batch with the name of its table. Threads, which are their messages
        taken together, come when the listing has ended."""
        wanted = [t for t in tables if t not in MESSAGE_TABLES]
        if wanted:
            raise KeyError(f"{', '.join(wanted)} do not come from a mailbox's messages")
        account = self.account
        whole = "messages" in tables
        unread: list[str] = [] if unreadable is None else unreadable
        seen: list[dict] = []
        listing = (
            self._messages(_MESSAGE_FIELDS, prefer=(_TEXT_BODY,))
            if whole
            else self._messages(_OTHER_FIELDS, prefer=())
        )
        for page in listing:
            if whole:
                html = self._html(page, unread)
                yield "messages", [message_row(account, m, html[m["id"]]) for m in page]
            if "message_recipients" in tables:
                yield "message_recipients", [r for m in page for r in recipient_rows(account, m)]
            if "message_folders" in tables:
                yield "message_folders", [message_folder_row(account, m) for m in page]
            if "attachments" in tables:
                for message in page:
                    if message["hasAttachments"]:
                        yield "attachments", self._attachments(message["id"])
            if "threads" in tables:
                seen += [
                    {
                        k: m.get(k)
                        for k in (
                            "id",
                            "conversationId",
                            "subject",
                            "bodyPreview",
                            "receivedDateTime",
                        )
                    }
                    for m in page
                ]
        if "threads" in tables:
            rows = thread_rows(account, seen)
            for start in range(0, len(rows), self._page_size):
                yield "threads", rows[start : start + self._page_size]
        if unread:
            log.warning(
                "microsoft_365 %s messages: %d message(s) kept without an HTML body Graph "
                "would not give: %s",
                account,
                len(unread),
                ", ".join(unread),
            )

    # ---------------------------------------------------------------- a read in units

    def _mine(self, **key: str) -> dict[str, Any]:
        return {"provider": PROVIDER, "account": self.account, **key}

    def _changes(
        self,
        tables: tuple[str, ...],
        page: list[dict],
        unread: list[str],
    ) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
        """The rows ``page`` (messages as Graph gives them) puts in ``tables``, and what they
        replace: each message's dependants are named by the message and replaced whole, so a
        recipient or an attachment the message no longer has does not stay."""
        account = self.account
        rows: dict[str, list[dict]] = {}
        removed: dict[str, list[dict]] = {}
        if "messages" in tables:
            html = self._html(page, unread)
            rows["messages"] = [message_row(account, m, html[m["id"]]) for m in page]
        of = [self._mine(message_id=m["id"]) for m in page]
        if "message_recipients" in tables:
            removed["message_recipients"] = of
            rows["message_recipients"] = [r for m in page for r in recipient_rows(account, m)]
        if "message_folders" in tables:
            removed["message_folders"] = of
            rows["message_folders"] = [message_folder_row(account, m) for m in page]
        if "attachments" in tables:
            removed["attachments"] = of
            rows["attachments"] = [
                a for m in page if m["hasAttachments"] for a in self._attachments(m["id"])
            ]
        return rows, removed

    def units(
        self,
        tables: tuple[str, ...] | list[str],
        kept: dict[str, str] | None = None,
        unreadable: list[str] | None = None,
    ) -> Iterator[Unit]:
        """The mailbox's messages as changes to ``tables``, a :class:`Unit` at a time.

        With nothing kept (``kept`` empty) the mailbox is read from its start: its rows in the
        tables are removed and it lands a page of messages at a time, each page with its
        messages' dependants; a folder's link is given when the folder has been read to its
        end, and the threads and the list of folders' link when every folder has.

        With links kept, each folder is asked what changed since its own (a folder met for the
        first time is read whole) and the mailbox's changes are ONE unit: a message moved
        between two folders is removed from one and added to the other, and only the two
        answers together say it is still there.

        A kept link Graph no longer honours, and a folder that was kept and is no longer
        listed, are answered by reading the mailbox from its start."""
        wanted = [t for t in tables if t not in MESSAGE_TABLES]
        if wanted:
            raise KeyError(f"{', '.join(wanted)} do not come from a mailbox's messages")
        tables = tuple(tables)
        unread: list[str] = [] if unreadable is None else unreadable
        folders = [f["id"] for page in self._folders() for f in page]
        kept = dict(kept or {})
        if kept and all(f in folders for f in kept if f != MAILBOX):
            try:
                yield self._since(tables, folders, kept, unread)
                return
            except GraphRefused as refused:
                if not _link_gone(refused):
                    raise
                log.warning(
                    "microsoft_365 %s: a kept link is no longer honoured; the mailbox is read "
                    "again from its start",
                    self.account,
                )
        yield from self._from_the_start(tables, folders, unread)

    def _round(self, folder: str, link: str | None, whole: bool) -> Any:
        prefer = (IMMUTABLE_IDS, f"odata.maxpagesize={self._page_size}")
        prefer += (_TEXT_BODY,) if whole else ()
        if link is not None:
            return self._graph.delta(link, prefer=prefer)
        fields = _MESSAGE_FIELDS if whole else _OTHER_FIELDS
        return self._graph.delta(
            f"{self._root}/mailFolders/{quote(folder, safe='')}/messages/delta",
            {"$select": fields if self._not_before is None else _DATED_FIELDS},
            prefer=prefer,
        )

    def _held_of(self, items: list[dict], whole: bool) -> list[dict]:
        """The messages of a round's ``items`` this source holds, with the fields its tables
        are made from."""
        return self._taken(
            items,
            _MESSAGE_FIELDS if whole else _OTHER_FIELDS,
            (_TEXT_BODY,) if whole else (),
        )

    def _folders_link(self, link: str | None) -> str:
        listed = self._graph.delta(
            link if link is not None else f"{self._root}/mailFolders/delta",
            None if link is not None else {"$select": "id"},
            prefer=(IMMUTABLE_IDS,),
        )
        for _page in listed:
            pass
        assert listed.link is not None  # the round was read to its end
        return listed.link

    def _from_the_start(
        self, tables: tuple[str, ...], folders: list[str], unread: list[str]
    ) -> Iterator[Unit]:
        whole = "messages" in tables
        # What the tables hold of this mailbox is replaced by what is read now.
        yield Unit(self.account, removed={t: [self._mine()] for t in tables}, forget=True)
        threads: list[dict] = []
        for folder in folders:
            changes = self._round(folder, None, whole)
            try:
                for page in changes:
                    # A first round removes none; a message older than the source's date is
                    # not held.
                    page = self._held_of([m for m in page if "@removed" not in m], whole)
                    if not page:
                        continue
                    rows, removed = self._changes(tables, page, unread)
                    yield Unit(self.account, rows=rows, removed=removed)
                    if "threads" in tables:
                        threads += [{k: m.get(k) for k in _THREAD_FIELDS} for m in page]
            except GraphRefused as refused:
                if not not_there(refused):
                    raise
                self._folder_gone(folder)
                continue
            assert changes.link is not None  # the round was read to its end
            yield Unit(self.account, links={folder: changes.link})
        last = Unit(self.account, links={MAILBOX: self._folders_link(None)}, last=True)
        if "threads" in tables:
            # A message moved while the folders were read is met twice: once is counted.
            once = list({m["id"]: m for m in threads}.values())
            last.rows["threads"] = thread_rows(self.account, once)
        yield last

    def _since(
        self, tables: tuple[str, ...], folders: list[str], kept: dict[str, str], unread: list[str]
    ) -> Unit:
        whole = "messages" in tables
        changed: dict[str, dict] = {}
        gone: set[str] = set()
        links: dict[str, str] = {}
        for folder in folders:
            changes = self._round(folder, kept.get(folder), whole)
            try:
                for page in changes:
                    gone.update(m["id"] for m in page if "@removed" in m)
                    for message in self._held_of([m for m in page if "@removed" not in m], whole):
                        changed[message["id"]] = message
            except GraphRefused as refused:
                if not not_there(refused):
                    raise
                # Removed after the folders were listed. It keeps no link: at the next read it
                # is a kept folder no longer listed, and the mailbox is read from its start,
                # which is what removes the rows of the messages that went with it.
                self._folder_gone(folder)
                continue
            assert changes.link is not None
            links[folder] = changes.link
        links[MAILBOX] = self._folders_link(kept.get(MAILBOX))
        gone -= set(changed)  # removed from one folder and met in another: moved, still there
        unit = Unit(self.account, links=links, last=True)
        messages = list(changed.values())
        for start in range(0, len(messages), self._page_size):
            rows, removed = self._changes(tables, messages[start : start + self._page_size], unread)
            for table, new in rows.items():
                unit.rows.setdefault(table, []).extend(new)
            for table, old in removed.items():
                unit.removed.setdefault(table, []).extend(old)
        for message_id in sorted(gone):
            for table in tables:
                if table == "messages":
                    unit.removed.setdefault(table, []).append(self._mine(id=message_id))
                elif table != "threads":
                    unit.removed.setdefault(table, []).append(self._mine(message_id=message_id))
        if "threads" in tables:
            # A thread is its messages taken together: each one a changed message is in is
            # worked out again from all its messages as they are now. A removed message does
            # not say which thread it was in, so its thread keeps its row until a whole read.
            touched = sorted({m["conversationId"] for m in messages})
            unit.rows["threads"] = [
                row
                for thread_id in touched
                for row in thread_rows(self.account, self._thread_messages(thread_id))
            ]
        return unit

    def _folder_gone(self, folder: str) -> None:
        log.info("microsoft_365 %s: folder %s is no longer there; skipped", self.account, folder)

    def _thread_messages(self, thread_id: str) -> list[dict]:
        quoted = thread_id.replace("'", "''")
        return [
            {k: m.get(k) for k in _THREAD_FIELDS}
            for page in self._graph.pages(
                f"{self._root}/messages",
                {"$filter": f"conversationId eq '{quoted}'", "$select": ",".join(_THREAD_FIELDS)},
                prefer=(IMMUTABLE_IDS,),
            )
            for m in page
            if self._held(m)  # a thread is counted from the messages the source holds
        ]

    def _attachments(self, message_id: str) -> list[dict[str, Any]]:
        path = f"{self._root}/messages/{quote(message_id, safe='')}/attachments"
        return [
            attachment_row(self.account, message_id, a)
            for items in self._graph.pages(
                path, {"$select": _ATTACHMENT_FIELDS}, prefer=(IMMUTABLE_IDS,)
            )
            for a in items
        ]

    def rows(
        self, table: str, unreadable: list[str] | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        """Every row of one of the mail tables, a batch at a time. A table that comes from
        the messages is read by the one reader of them (:meth:`message_tables`), as a group
        of one; folders are their own read."""
        if table in MESSAGE_TABLES:
            for _table, rows in self.message_tables((table,), unreadable):
                yield rows
        elif table == "folders":
            known = self._well_known()
            for page in self._folders():
                yield [folder_row(self.account, f, known.get(f["id"])) for f in page]
        else:
            raise KeyError(f"{table!r} is not a Microsoft 365 mail table")
