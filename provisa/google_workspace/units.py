# Copyright (c) 2026 Kenneth Stott
# Canary: aebe5645-93da-4a77-b7d3-bd0752d2afc6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""One Gmail mailbox as units to be written in place (``core.canonical_mail.Unit``,
``federation.mail_units.ReplicaUnitJob``): a part of the mailbox at a time, readable as soon as
it lands, from where the last read reached.

- **From its start.** A mailbox never read, one Google no longer has the kept history record
  of, and every read of a source that narrows by Gmail's own search (only Google can say what
  a search matches): the mailbox's rows are cleared in the first unit, its messages follow a
  page at a time, and its threads -- each added up over all its messages -- come in the last.
- **Its changes.** Otherwise ONE unit: what Gmail's history says happened since the kept
  record. A message added, or given or relieved of a label, is fetched again and its
  recipients, folders and attachments are replaced whole; a message deleted, gone when it is
  fetched, or no longer among the mail the source holds, is removed with them. The threads of
  all of these are read again from Gmail and replaced, or removed when none of their messages
  is held any more -- Gmail's history names a deleted message's thread, so this is exact.
The mailbox's labels (``folders``) are not part of this: they are read whole, on their own, as
before.

Where a read reached is the mailbox's history id AS IT STOOD WHEN THE READ BEGAN, given with
the mailbox's last unit: a change made while it was read is then read again, and writing it
again leaves the same rows.
"""

# Requirements: REQ-1923
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

from provisa.core import canonical_mail as cm
from provisa.google_workspace.gmail import Gmail, GmailNotFound
from provisa.google_workspace.mail_rows import PROVIDER, MessageFacts, message_facts
from provisa.google_workspace.settings import MAIL_HEADERS, MailSettings

#: The scope a mailbox's position is kept under: the mailbox itself.
MAILBOX = ""
#: A message's own rows in other tables, each named by the message's id.
DEPENDANTS: tuple[str, ...] = ("message_recipients", "message_folders", "attachments")
_NOT_HELD = frozenset({"SPAM", "TRASH"})
_PER_MESSAGE = {
    "messages": lambda facts: [facts.message],
    "message_recipients": lambda facts: facts.recipients,
    "message_folders": lambda facts: facts.folders,
    "attachments": lambda facts: facts.attachments,
}
#: Tables whose rows need a message's text or parts; without them headers and labels do.
_NEEDS_WHOLE_MESSAGE = frozenset({"messages", "attachments"})


def held(answered: dict, mail: MailSettings, label_ids: list[str]) -> bool:
    """Whether a message is among the mail the source holds, by what can be told from the
    message itself: it carries every label the source names, is not in spam or the bin unless
    the source takes those, and was not received before the source's first day. A source that
    narrows by Gmail's search is never asked this (:func:`mailbox_units`)."""
    labels = set(answered.get("labelIds") or [])
    if not mail.include_spam_trash and labels & _NOT_HELD:
        return False
    if any(label not in labels for label in label_ids):
        return False
    if mail.since is not None:
        midnight = dt.datetime.combine(mail.since, dt.time(), dt.timezone.utc)
        return int(answered.get("internalDate") or 0) >= int(midnight.timestamp() * 1000)
    return True


def _of(account: str, **more: Any) -> dict[str, Any]:
    return {"provider": PROVIDER, "account": account, **more}


def _rows(page: list[MessageFacts], tables: tuple[str, ...]) -> dict[str, list[dict]]:
    rows = {
        table: [row for facts in page for row in _PER_MESSAGE[table](facts)]
        for table in tables
        if table in _PER_MESSAGE
    }
    return {table: found for table, found in rows.items() if found}


async def mailbox_units(
    gmail: Gmail,
    mail: MailSettings,
    tables: tuple[str, ...],
    kept: dict[str, str] | None,
    history: str,
    unreadable: list[str],
    *,
    threads: Any,
    messages: Any,
) -> AsyncIterator[cm.Unit]:
    """The units of one mailbox: its changes since ``kept`` where Gmail can say them, else the
    mailbox from its start. ``history`` is its history id as the read began. ``threads`` and
    ``messages`` are the loader's own adder-up of threads and reader of pages of messages, so
    a unit's rows are the rows a whole build gives."""
    if not _NEEDS_WHOLE_MESSAGE.intersection(tables):
        mail = MailSettings(
            MAIL_HEADERS, mail.search, mail.labels, mail.since, mail.include_spam_trash
        )
    since = (kept or {}).get(MAILBOX)
    if since is not None and not mail.search:
        try:
            changed, gone = await _history(gmail, since)
        except GmailNotFound:
            pass  # Google no longer has the record: nothing says what changed since
        else:
            yield await _changes(gmail, mail, tables, history, changed, gone, unreadable, threads)
            return
    account = gmail.account
    yield cm.Unit(account, removed={table: [_of(account)] for table in tables}, forget=True)
    totals = threads(account) if "threads" in tables else None
    async for page in messages(gmail, mail, unreadable):
        if totals is not None:
            for facts in page:
                totals.add(facts.message)
        yield cm.Unit(account, rows=_rows(page, tables))
    last = cm.Unit(account, links={MAILBOX: history}, last=True)
    if totals is not None:
        last.rows["threads"] = totals.rows()
    yield last


async def _history(gmail: Gmail, since: str) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """The messages Gmail's history names since ``since``, each with its thread: those added
    or relabelled, and those deleted. A message deleted in the end is only that."""
    changed: dict[str, str | None] = {}
    gone: dict[str, str | None] = {}
    async for records in gmail.history(since):
        for record in records:
            for kind in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                for entry in record.get(kind) or []:
                    message = entry["message"]
                    changed[message["id"]] = message.get("threadId")
                    gone.pop(message["id"], None)
            for entry in record.get("messagesDeleted") or []:
                message = entry["message"]
                gone[message["id"]] = message.get("threadId")
                changed.pop(message["id"], None)
    return changed, gone


async def _changes(
    gmail: Gmail,
    mail: MailSettings,
    tables: tuple[str, ...],
    history: str,
    changed: dict[str, str | None],
    gone: dict[str, str | None],
    unreadable: list[str],
    threads: Any,
) -> cm.Unit:
    account = gmail.account
    unit = cm.Unit(account, links={MAILBOX: history}, last=True)
    label_ids = await gmail.label_ids(mail.labels)
    page: list[MessageFacts] = []
    for message_id, thread_id in changed.items():
        try:
            answered = await gmail.message(message_id, mail)
        except GmailNotFound:
            gone[message_id] = thread_id  # deleted since the history named it
            continue
        if not held(answered, mail, label_ids):
            gone[message_id] = thread_id or answered.get("threadId")
            continue
        facts = message_facts(account, answered)
        if facts.unreadable is not None:
            unreadable.append(message_id)
        page.append(facts)
    # A message's dependants are replaced whole, and go with a message that went.
    touched = [*gone, *(facts.message["id"] for facts in page)]
    for table in DEPENDANTS:
        if table in tables and touched:
            unit.removed[table] = [_of(account, message_id=message_id) for message_id in touched]
    if "messages" in tables and gone:
        unit.removed["messages"] = [_of(account, id=message_id) for message_id in gone]
    unit.rows.update(_rows(page, tables))
    if "threads" in tables:
        await _threads(gmail, mail, label_ids, unit, page, gone, threads)
    return unit


async def _threads(
    gmail: Gmail,
    mail: MailSettings,
    label_ids: list[str],
    unit: cm.Unit,
    page: list[MessageFacts],
    gone: dict[str, str | None],
    threads: Any,
) -> None:
    """The threads of the messages that changed or went, read again from Gmail: a thread is its
    held messages taken together, so one message's change is the thread's."""
    account = gmail.account
    ids = {facts.message["thread_id"] for facts in page} | set(gone.values())
    rows: list[dict] = []
    removed: list[dict] = []
    for thread_id in sorted(t for t in ids if t):
        try:
            answered = await gmail.thread(thread_id)
        except GmailNotFound:
            removed.append(_of(account, id=thread_id))
            continue
        totals = threads(account)
        for message in answered.get("messages") or []:
            if held(message, mail, label_ids):
                totals.add(message_facts(account, message).message)
        found = totals.rows()
        if found:
            rows += found
        else:
            removed.append(_of(account, id=thread_id))
    if rows:
        unit.rows["threads"] = rows
    if removed:
        unit.removed["threads"] = removed
