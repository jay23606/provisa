# Copyright (c) 2026 Kenneth Stott
# Canary: 07e57a0f-f4e1-4794-985c-a4d00d83cdce
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The mail tables of a Google Workspace source (REQ-1923).

One source reads one mailbox and offers the six canonical mail tables
(``provisa.core.canonical_mail``): ``messages``, ``message_recipients``, ``folders``,
``message_folders``, ``threads`` and ``attachments``. Each is read whole, from Gmail, into rows
of exactly the canonical columns, and landed as a replica like any fetched source.

The five tables that come from messages are ONE read (:func:`message_table_rows`): the mailbox
is listed once and each message fetched once, whichever of them are being built, as headers
and labels only when none of them needs a message's text. A replica build takes them together
(``replica_group``, ``federation.data_replicator.ReplicaGroupJob``). ``folders`` comes from
the mailbox's labels, on its own. Nothing is held in memory beyond a page and what ``threads``
adds up.

A message with a part that is not what it declares keeps its row without text
(``mail_rows``); the read counts such messages and names them when it ends: every id in the
log, and the count with the first of their ids as the build's note on the replica
(``data_replicator.unreadable_messages_note``).
"""

# Requirements: REQ-1923
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from provisa.core import canonical_mail as cm
from provisa.federation.data_replicator import noted, unreadable_messages_note
from provisa.google_workspace import settings as gw_settings
from provisa.google_workspace.gmail import Gmail, GmailNotFound, GmailRefused, QuotaExhausted
from provisa.google_workspace.mail_rows import PROVIDER, MessageFacts, message_facts
from provisa.google_workspace.settings import MAIL_HEADERS, MailSettings, Settings

log = logging.getLogger(__name__)

#: The canonical tables this source offers, in the order the table picker lists them.
TABLES: tuple[str, ...] = (
    "messages",
    "message_recipients",
    "folders",
    "message_folders",
    "threads",
    "attachments",
)
#: The schema the table picker shows them under: a mailbox has none of its own.
SCHEMA = "default"

#: Tables whose rows need a message's text and parts; every other is read as headers only.
_NEEDS_WHOLE_MESSAGE = frozenset({"messages", "attachments"})
_PER_MESSAGE = {
    "messages": lambda facts: [facts.message],
    "message_recipients": lambda facts: facts.recipients,
    "message_folders": lambda facts: facts.folders,
    "attachments": lambda facts: facts.attachments,
}


class UnknownMailTable(LookupError):
    def __init__(self, table: str) -> None:
        super().__init__(
            f"A Google Workspace source has no table {table!r}; it offers {', '.join(TABLES)}"
        )


def source_settings(source: Any) -> Settings:
    """The source's settings, as its mapping states them. Credentials stay references."""
    return gw_settings.parse(dict(getattr(source, "mapping", None) or {}))


async def _resolved(admin_db: Any, org_id: str, auth: Any) -> Any:
    """``auth`` ready to use: the organisation's client secret and the owner's approval as their
    fields hold them -- a value, or a reference someone typed -- resolved in ``org_id``'s vault,
    here on the event loop: the token exchange runs in a worker thread, which holds no vault.
    The vault is bound for these reads and never taken from the caller."""
    from provisa.core import mail_platforms
    from provisa.google_workspace import SOURCE_TYPE

    client_secret = await mail_platforms.credential(
        admin_db, org_id, SOURCE_TYPE, mail_platforms.CLIENT_SECRET, auth.client_secret
    )
    refresh_token = await mail_platforms.resolved(admin_db, org_id, auth.refresh_token)
    return auth.model_copy(update={"client_secret": client_secret, "refresh_token": refresh_token})


def _folder(account: str, label: dict) -> dict[str, Any]:
    kind = label.get("type")
    color = label.get("color") or {}
    list_visibility = label.get("labelListVisibility")
    return {
        "provider": PROVIDER,
        "account": account,
        "id": label["id"],
        "name": label.get("name"),
        "parent_id": None,
        "kind": cm.translate("folder_kind", cm.GOOGLE, kind),
        # Google names a system label's role by its id; a label of the user's own has none.
        "role": cm.translate("folder_role", cm.GOOGLE, label["id"]) if kind == "system" else None,
        "is_hidden": None if list_visibility is None else list_visibility == "labelHide",
        "total_count": label.get("messagesTotal"),
        "unread_count": label.get("messagesUnread"),
        "child_count": None,
        "threads_total": label.get("threadsTotal"),
        "threads_unread": label.get("threadsUnread"),
        "color_text": color.get("textColor"),
        "color_background": color.get("backgroundColor"),
        "message_list_visibility": cm.translate(
            "message_list_visibility", cm.GOOGLE, label.get("messageListVisibility")
        ),
        "label_list_visibility": cm.translate("label_list_visibility", cm.GOOGLE, list_visibility),
    }


class _Threads:
    """The threads of the messages read: each thread's first subject, last snippet, span and
    count."""

    def __init__(self, account: str) -> None:
        self._account = account
        self._by_id: dict[str, dict[str, Any]] = {}
        self._undated = 0

    def add(self, message: dict[str, Any]) -> None:
        thread_id, at = message["thread_id"], message["received_at"]
        if thread_id is None:
            return
        thread = self._by_id.setdefault(
            thread_id,
            {
                "provider": PROVIDER,
                "account": self._account,
                "id": thread_id,
                "subject": None,
                "snippet": None,
                "first_message_at": None,
                "last_message_at": None,
                "message_count": 0,
            },
        )
        thread["message_count"] += 1
        if at is None:
            return
        if thread["first_message_at"] is None or at < thread["first_message_at"]:
            thread["first_message_at"], thread["subject"] = at, message["subject"]
        if thread["last_message_at"] is None or at >= thread["last_message_at"]:
            thread["last_message_at"], thread["snippet"] = at, message["snippet"]

    def rows(self) -> list[dict[str, Any]]:
        return list(self._by_id.values())


async def _messages(
    gmail: Gmail, mail: MailSettings, unreadable: list[str]
) -> AsyncIterator[list[MessageFacts]]:
    """Every message of the mailbox the source holds, a page of ids at a time. A message
    deleted between its listing and its reading is no longer in the mailbox, and is not a row."""
    async for ids in gmail.message_ids(mail):
        page: list[MessageFacts] = []
        for message_id in ids:
            try:
                answered = await gmail.message(message_id, mail)
            except GmailNotFound:
                continue
            facts = message_facts(gmail.account, answered)
            if facts.unreadable is not None:
                unreadable.append(message_id)
            page.append(facts)
        yield page


#: The tables one read of the mailbox's messages gives; ``folders`` comes from its labels.
MESSAGE_TABLES: tuple[str, ...] = (
    "messages",
    "message_recipients",
    "message_folders",
    "attachments",
    "threads",
)


async def message_table_rows(
    gmail: Gmail, mail: MailSettings, tables: tuple[str, ...], unreadable: list[str]
) -> AsyncIterator[tuple[str, list[dict]]]:
    """The rows of the message tables ``tables``, from ONE pass over the mailbox: each message
    is fetched once and gives its rows to every table asked for. A page of messages yields
    each table's rows of that page; ``threads`` is added up over the whole pass and comes last.
    Whole messages are fetched only when a table asked for needs their text or parts. The ids
    of the messages kept without text are added to ``unreadable`` as they are met."""
    unknown = [table for table in tables if table not in MESSAGE_TABLES]
    if unknown:
        raise UnknownMailTable(unknown[0])
    if not _NEEDS_WHOLE_MESSAGE.intersection(tables):
        mail = MailSettings(
            MAIL_HEADERS, mail.search, mail.labels, mail.since, mail.include_spam_trash
        )
    threads = _Threads(gmail.account) if "threads" in tables else None
    async for page in _messages(gmail, mail, unreadable):
        for table in tables:
            if table == "threads":
                continue
            rows = [row for facts in page for row in _PER_MESSAGE[table](facts)]
            if rows:
                yield table, rows
        if threads is not None:
            for facts in page:
                threads.add(facts.message)
    if threads is not None:
        yield "threads", threads.rows()
    if unreadable:
        # Stated, never silent: these rows are in their tables without their text.
        log.warning(
            "Google Workspace mailbox %s, tables %s: %d message(s) have a part that is not "
            "what it declares and were kept without text: %s",
            gmail.account,
            ", ".join(tables),
            len(unreadable),
            ", ".join(unreadable),
        )


#: The build's note for the messages kept without text: the one every mail source gives.
unreadable_note = unreadable_messages_note


async def table_rows(
    gmail: Gmail, mail: MailSettings, table: str, unreadable: list[str] | None = None
) -> AsyncIterator[list[dict]]:
    """The rows of one canonical table, in batches, to the last one: ``folders`` from the
    mailbox's labels, any other from the one read of its messages, asked for that table alone."""
    if table not in TABLES:
        raise UnknownMailTable(table)
    if table == "folders":
        rows = []
        for label in await gmail.labels():
            rows.append(_folder(gmail.account, await gmail.label(label["id"])))
        yield rows
        return
    unreadable = [] if unreadable is None else unreadable
    async for _table, rows in message_table_rows(gmail, mail, (table,), unreadable):
        yield rows


@dataclass(frozen=True)
class Reading:
    """What reading a source needs, made where the organisation's vault is bound: the
    mailboxes to read, by address and in address order; which mail of each to hold; the call
    that answers the access token a mailbox is read with; and, for a source of the
    organisation's mailboxes, how many are read at once."""

    accounts: tuple[str, ...]
    mail: MailSettings
    token: Callable[[str], Awaitable[str]]
    organisation: bool = False
    at_once: int = 1
    #: Keeps where a completed read of the source reached (``federation.mail_sync_state``
    #: rows): called once the build that read to it is recorded as completed.
    keep: Callable[[dict[tuple[str, str, str], str]], Awaitable[None]] | None = None


Connect = Callable[[Any], Awaitable[Reading]]

#: What is kept for a mailbox the last completed read left out, in place of its history id.
LEFT_OUT = "left_out"
#: What Gmail answers for a user whose mail service is not turned on (HTTP 400).
_NO_MAIL_SERVICE = "failedPrecondition"


class NoMailboxRead(RuntimeError):
    """Not one of the organisation's mailboxes could be read: what is wrong is the setup, not
    a mailbox."""

    def __init__(self, count: int, reason: str) -> None:
        super().__init__(
            f"none of the {count} mailboxes could be read ({reason}): check that these "
            "addresses are users of the organisation's Google Workspace domain with Gmail "
            "turned on"
        )


def _not_readable(refused: BaseException) -> str | None:
    """Why a mailbox is one Google will not let be read at all, or None for any other failure:
    the address is no user of the domain, the user's mail service is not turned on, or there
    is no such mailbox. Throttling and the project's allowance are never this."""
    from provisa.google_workspace.directory import NotAUser

    if isinstance(refused, NotAUser):
        return refused.reason
    if isinstance(refused, QuotaExhausted):
        return None
    if isinstance(refused, GmailNotFound):
        return f"{refused.status} {refused.reason}"
    if isinstance(refused, GmailRefused) and refused.status == 400:
        return f"{refused.status} {refused.reason}" if _NO_MAIL_SERVICE in refused.reason else None
    return None


def _mailbox(reading: Reading, account: str, client: httpx.AsyncClient) -> Gmail:
    async def token() -> str:
        return await reading.token(account)

    return Gmail(account, token, client, quota_user=reading.organisation)


async def _read_mailboxes(
    reading: Reading,
    read: Callable[[Gmail], AsyncIterator[Any]],
    left_out: list[str],
    reached: dict[str, str] | None = None,
) -> AsyncIterator[Any]:
    """What ``read`` gives for each mailbox of ``reading``, as it arrives. Each mailbox is
    first asked for its profile: its current history id (kept in ``reached`` once the mailbox
    has been read to its end) and the proof that Google lets it be read. One mailbox is read
    as it stands: whatever Google refuses fails the read. The organisation's mailboxes are
    started in address order, ``at_once`` at a time; one Google will not let be read at all
    (:func:`_not_readable`, at its profile) is added to ``left_out`` and the others go on.
    Throttling Google does not lift, the project's allowance, a scope the domain has not
    delegated, and any refusal after a mailbox began to be read, fail the read."""
    async with httpx.AsyncClient() as client:

        async def rows_of(account: str) -> AsyncIterator[Any]:
            gmail = _mailbox(reading, account, client)
            history = (await gmail.profile())["historyId"]
            async for item in read(gmail):
                yield item
            if reached is not None:
                reached[account] = str(history)

        if not reading.organisation:
            (account,) = reading.accounts
            async for item in rows_of(account):
                yield item
            return

        waiting = list(reading.accounts)
        arrived: asyncio.Queue[Any] = asyncio.Queue(maxsize=max(reading.at_once, 1) * 2)
        last_refusal: list[str] = []

        async def worker() -> None:
            while waiting:
                account = waiting.pop(0)
                began = False
                try:
                    async for item in rows_of(account):
                        began = True
                        await arrived.put(item)
                except Exception as refused:  # allow-ble: only a mailbox Google will not let be read at all is taken here; every other failure is re-raised unchanged
                    why = None if began else _not_readable(refused)
                    if why is None:
                        raise
                    left_out.append(account)
                    last_refusal[:] = [why]

        workers = [
            asyncio.ensure_future(worker())
            for _ in range(max(min(reading.at_once, len(waiting)), 1))
        ]
        done = asyncio.ensure_future(asyncio.gather(*workers))
        try:
            while True:
                getter = asyncio.ensure_future(arrived.get())
                finished, _ = await asyncio.wait(
                    {getter, done}, return_when=asyncio.FIRST_COMPLETED
                )
                if getter in finished:
                    yield getter.result()
                    continue
                getter.cancel()
                done.result()  # raises what a worker raised
                while not arrived.empty():
                    yield arrived.get_nowait()
                break
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        if reading.accounts and len(left_out) == len(reading.accounts):
            raise NoMailboxRead(len(reading.accounts), last_refusal[0])
        if left_out:
            log.warning(
                "google_workspace: %d of %d mailbox(es) were left out, not there or not "
                "permitted: %s",
                len(left_out),
                len(reading.accounts),
                ", ".join(sorted(left_out)),
            )


def _notes(unreadable: list[str], left_out: list[str]) -> list[Any]:
    from provisa.federation.data_replicator import mailboxes_left_out_note

    return noted(unreadable_note(unreadable), mailboxes_left_out_note(sorted(left_out)))


class _MailboxRead:
    """One read of a source's mailboxes as the rows of several message tables: what a group
    build streams (``federation.data_replicator.ReplicaGroupJob``)."""

    def __init__(
        self,
        connect: Connect,
        source: Any,
        tables: tuple[str, ...],
        columns: dict[str, list[tuple[str, str]]],
    ) -> None:
        from provisa.federation.data_replicator import SourceCaps, SourceRead

        self.caps = SourceCaps(frozenset({SourceRead.CURSOR}))
        self._connect = connect
        self._source = source
        self._tables = tables
        self._columns = columns
        self._unreadable: list[str] = []
        self._left_out: list[str] = []
        self._reached: dict[str, str] = {}
        self._reading: Reading | None = None

    def notes(self) -> list[Any]:
        return _notes(self._unreadable, self._left_out)

    async def committed(self) -> None:
        """Keep where this read reached, now that the build it fed is recorded as completed
        (the replica runner awaits this then, and never for a failed build): each read
        mailbox's history id as it stood when its read BEGAN, so a change made while it was
        read is seen as one. A mailbox left out is kept as that. What was kept for a mailbox
        this read did not see is forgotten with the same write.

        Nothing is kept by a read that did not read every one of its mailboxes to the end."""
        from provisa.federation.mail_sync_state import PROBE

        reading = self._reading
        if reading is None or reading.keep is None:
            return
        gone = set(self._left_out)
        if set(self._reached) != set(reading.accounts) - gone:
            return
        rows = {(account, "", PROBE): history for account, history in self._reached.items()}
        rows.update({(account, "", PROBE): LEFT_OUT for account in gone})
        await reading.keep(rows)

    async def batches(self, batch_rows: int) -> AsyncIterator[tuple[str, Any]]:
        from provisa.core.ir_arrow import arrow_schema, rows_to_batch

        # A build reads once; a read begun again counts again.
        self._unreadable.clear()
        self._left_out.clear()
        self._reached.clear()
        schemas = {table: arrow_schema(self._columns[table]) for table in self._tables}
        reading = self._reading = await self._connect(self._source)
        async for table, rows in _read_mailboxes(
            reading,
            lambda gmail: message_table_rows(gmail, reading.mail, self._tables, self._unreadable),
            self._left_out,
            self._reached,
        ):
            for start in range(0, len(rows), batch_rows):
                yield (
                    table,
                    rows_to_batch(
                        rows[start : start + batch_rows], self._columns[table], schemas[table]
                    ),
                )


async def mailbox_token(connect: Connect, source: Any) -> str | None:
    """The opaque token of the source's mailboxes as they stand now: a digest of each address
    with the id of its current history record (Gmail's ``users.getProfile``, one quota unit a
    mailbox). Gmail records a history entry when a message is added or deleted and when its
    labels change, so an equal token is mailboxes nothing has happened to. A mailbox Google
    will not let be read at all is in the digest as that, so one that stays unreadable changes
    nothing and one that becomes readable does.

    None when Google cannot be asked -- refused, throttled past the client's retries, the
    sign-in not renewable, the organisation's credential not entered or not delegated, the
    directory not listed. None is never "unchanged": the caller then asks for a read, and the
    read reports the reason on the replica."""
    from provisa.api_source.caller import ApiCallError
    from provisa.core.mail_platforms import MailPlatformRefused
    from provisa.google_workspace import directory

    try:
        reading = await connect(source)
        gate = asyncio.Semaphore(max(reading.at_once, 1))
        async with httpx.AsyncClient() as client:

            async def seen(account: str) -> str:
                async with gate:
                    try:
                        profile = await _mailbox(reading, account, client).profile()
                    except Exception as refused:  # allow-ble: only a mailbox Google will not let be read at all is taken here; every other failure is re-raised unchanged
                        if not reading.organisation or _not_readable(refused) is None:
                            raise
                        return f"{account}\x00{LEFT_OUT}"
                return f"{account}\x00{profile['historyId']}"

            lines = await asyncio.gather(*(seen(account) for account in reading.accounts))
    except (
        GmailRefused,
        ApiCallError,
        MailPlatformRefused,
        directory.DelegationRefused,
        directory.DirectoryRefused,
        directory.NotAUser,
        httpx.HTTPError,
    ) as cannot:
        log.warning(
            "Google Workspace source %s: its mailboxes could not be asked whether they "
            "changed (%s); a read is asked for instead",
            source.id,
            cannot,
        )
        return None
    if not lines:
        return None  # no mailbox to ask: that is not "unchanged"
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def make_google_workspace_loader(connect: Connect) -> Any:
    """The row-fetch of a Google Workspace source: one of its tables, whole, read from Google
    as ``connect`` signs the source in."""

    async def _batches(
        source: Any,
        table: Any,
        unreadable: list[str] | None = None,
        left_out: list[str] | None = None,
    ) -> AsyncIterator[list[dict]]:
        name = table.table_name
        if name not in TABLES:
            raise UnknownMailTable(name)
        reading = await connect(source)
        async for rows in _read_mailboxes(
            reading,
            lambda gmail: table_rows(gmail, reading.mail, name, unreadable),
            [] if left_out is None else left_out,
        ):
            if rows:
                yield rows

    async def _load(source: Any, table: Any) -> list[dict]:
        return [row async for rows in _batches(source, table) for row in rows]

    def _replica_source(source: Any, table: Any, columns: list[tuple[str, str]]) -> Any:
        from provisa.federation.replica_source import CursorSource

        unreadable: list[str] = []
        left_out: list[str] = []

        def read(_batch_rows: int) -> AsyncIterator[list[dict]]:
            # A build reads once; a read begun again counts again.
            unreadable.clear()
            left_out.clear()
            return _batches(source, table, unreadable, left_out)

        return CursorSource(read, columns, notes=lambda: _notes(unreadable, left_out))

    def _freshness_probe(source: Any, table: Any) -> Any:
        """The table's change probe (REQ-855, REQ-982), for a table read from the mailboxes:
        their messages or their labels. None for any other table: it has no cheap token."""
        if table.table_name not in TABLES:
            return None

        async def token() -> str | None:
            return await mailbox_token(connect, source)

        return token

    def _replica_group(_source: Any, table: Any) -> tuple[str, ...] | None:
        """The tables one read of the mailboxes gives together with ``table``, or None when
        ``table`` is read on its own (folders)."""
        return MESSAGE_TABLES if table.table_name in MESSAGE_TABLES else None

    def _replica_group_source(
        source: Any, tables: tuple[str, ...], columns: dict[str, list[tuple[str, str]]]
    ) -> Any:
        return _MailboxRead(connect, source, tuple(tables), columns)

    _load.replica_source = _replica_source  # type: ignore[attr-defined]
    _load.freshness_probe = _freshness_probe  # type: ignore[attr-defined]
    _load.replica_group = _replica_group  # type: ignore[attr-defined]
    _load.replica_group_source = _replica_group_source  # type: ignore[attr-defined]
    return _load


async def organisation_account(admin_db: Any, org_id: str) -> tuple[Any, str]:
    """The organisation's Google service account and the administrator address directory calls
    are made as, for reading the organisation's mailboxes: refused by name unless its
    administrator has allowed such sources. The key is resolved here in the organisation's own
    vault, which no caller need have bound (a source of the organisation's mailboxes names no
    secret of its own, so a replica build binds none for it), and held only by the account."""
    from provisa.core import mail_platforms
    from provisa.google_workspace import SOURCE_TYPE
    from provisa.google_workspace.directory import ServiceAccount

    entry = await mail_platforms.require_organisation(admin_db, org_id, SOURCE_TYPE)
    admin = entry.settings.get("admin_address")
    if entry.organisation_key is None or not admin:
        # require_organisation's switch cannot be on without both (mail_platforms.put).
        raise mail_platforms.MailPlatformRefused(
            "incomplete",
            f"{SOURCE_TYPE} needs organisation_key, admin_address",
            missing="organisation_key, admin_address",
        )
    key = await mail_platforms.credential(
        admin_db, org_id, SOURCE_TYPE, mail_platforms.ORGANISATION_KEY, entry.organisation_key
    )
    return ServiceAccount(key), admin


async def listed_mailboxes(account: Any, admin: str, chosen: Any) -> list[str]:
    """The mailboxes ``chosen`` names, as the directory lists them now, read off the event
    loop as the organisation's administrator."""
    from provisa.google_workspace import directory

    def listed() -> list[str]:
        with httpx.Client() as http:
            return directory.mailboxes(
                directory.Directory(lambda scope: account.token(admin, (scope,)), http), chosen
            )

    return await asyncio.to_thread(listed)


def make_connect(state: Any) -> Connect:
    """How a source is signed in for a read: one mailbox with its owner's approval of the
    organisation's Google client; the organisation's mailboxes with its service account,
    reading as each user."""
    from provisa.api_source.oauth_grants import access_token
    from provisa.core import mail_platforms, settings_registry
    from provisa.core.request_context import require_current_org
    from provisa.google_workspace import SOURCE_TYPE

    async def connect(source: Any) -> Reading:
        settings = source_settings(source)
        if settings.mail is None:
            raise UnknownMailTable("messages")
        org_id = require_current_org()

        async def keep(rows: dict[tuple[str, str, str], str]) -> None:
            from provisa.federation import mail_sync_state

            async with state.tenant_db.acquire() as conn:
                await mail_sync_state.replace(conn, source.id, rows)

        if settings.organisation:
            assert settings.mailboxes is not None  # the organisation shape names its mailboxes
            # Refused by name unless the organisation's administrator allowed sources that
            # read its mailboxes: asked here, each time a credential is about to be used.
            account, admin = await organisation_account(state.admin_db, org_id)
            scopes = tuple(settings.scopes())

            async def as_user(address: str) -> str:
                return await asyncio.to_thread(account.token, address, scopes)

            return Reading(
                tuple(await listed_mailboxes(account, admin, settings.mailboxes)),
                settings.mail,
                as_user,
                organisation=True,
                at_once=int(settings_registry.value("mail.mailboxes_at_once")),
                keep=keep,
            )
        client = await mail_platforms.require(state.admin_db, org_id, SOURCE_TYPE)
        (address,) = settings.accounts
        # Resolved here, in the organisation's vault: the exchange runs in a worker thread,
        # which holds none.
        auth = await _resolved(state.admin_db, org_id, settings.auth(address, client))

        async def signed_in(_address: str) -> str:
            return await asyncio.to_thread(access_token, auth)

        return Reading((address,), settings.mail, signed_in, keep=keep)

    return connect
