# Copyright (c) 2026 Kenneth Stott
# Canary: 18728d2e-6c20-44d3-81c1-52c306635a89
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Live Google Workspace source of the organisation's mailboxes (REQ-1923), against a real
Workspace domain.

What it proves that a stand-in Google cannot: Google issues the service account a token to
read as a user and as the administrator (the domain has delegated the scopes); the Directory
API lists the test mailboxes; ONE read of a mailbox feeds the five message tables with the
canonical columns; a suspended user is not listed and, when named, is left out and named in
the build's note; a completed read keeps each mailbox's history id, and asking at once says
nothing changed.

Nothing is written to the domain. No server, engine or container is used: the loader is driven
directly, so run it with the stack switched off:

    PYTEST_NO_DOCKER=1 .venv/bin/python3 -m pytest \\
        tests/integration/test_google_workspace_live_e2e.py -o addopts="" -q

Credentials
-----------
There is no Google Workspace emulator: a real domain, and a service account whose client ID a
super administrator has authorised (Admin console, Security > Access and data control > API
controls > Manage Domain Wide Delegation) for these scopes, are required:

    https://www.googleapis.com/auth/gmail.readonly
    https://www.googleapis.com/auth/admin.directory.user.readonly
    https://www.googleapis.com/auth/admin.directory.group.member.readonly

Read from the environment (``.env`` through tests/env_creds.py):

  GWS_SERVICE_ACCOUNT_KEY_FILE  the PATH of the service account's JSON key file. The key
                                itself is never put in an environment variable.
  GWS_ADMIN_ADDRESS             an administrator of the domain; directory calls are made as it
  GWS_TEST_MAILBOXES            comma-separated addresses of users of the domain; SMALL
                                mailboxes, each holding at least one message -- a whole
                                mailbox is read
  GWS_TEST_MAILBOX_SUSPENDED    optional: one suspended user of the domain

Like the live Microsoft 365 and Salesforce tests it is in no CI lane (the domain is the
maintainer's own; CI holds no Workspace key), and like every warehouse test a credential that
is not set fails it by name rather than passing it over (tests/skip_is_failure.py).

Neither the key nor an access token is put in an assertion message, a log line or captured
output; the last test asserts it.
"""

# Requirements: REQ-1923
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
import pytest

from tests.env_creds import unset

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_warehouse,
    pytest.mark.requires_google_workspace,
]

_ENV = ("GWS_SERVICE_ACCOUNT_KEY_FILE", "GWS_ADMIN_ADDRESS", "GWS_TEST_MAILBOXES")
_HAVE_CREDS = all(os.environ.get(v) for v in _ENV)
pytestmark.append(pytest.mark.skipif(not _HAVE_CREDS, reason=f"not set: {unset(*_ENV)}"))

from provisa.core import canonical_mail as cm  # noqa: E402
from provisa.federation.data_replicator import MAILBOXES_LEFT_OUT  # noqa: E402
from provisa.federation.mail_sync_state import PROBE  # noqa: E402
from provisa.google_workspace import directory, loader  # noqa: E402
from provisa.google_workspace import settings as gws  # noqa: E402

#: How long one whole-mailbox read may take before the test says the mailbox is not a small one.
_READ_SECONDS = 900
_MAIL = gws.MailSettings(gws.MAIL_FULL, None, (), None, False)
_MAIL_SCOPE = (gws.MAIL_SCOPES[gws.MAIL_FULL],)


def _inside() -> tuple[str, ...]:
    return tuple(
        a.strip().lower() for a in os.environ["GWS_TEST_MAILBOXES"].split(",") if a.strip()
    )


def _suspended() -> str | None:
    address = os.environ.get("GWS_TEST_MAILBOX_SUSPENDED", "").strip().lower()
    return address or None


def _admin() -> str:
    return os.environ["GWS_ADMIN_ADDRESS"].strip()


def _key() -> str:
    return Path(os.environ["GWS_SERVICE_ACCOUNT_KEY_FILE"]).expanduser().read_text()


@pytest.fixture(scope="module")
def account() -> directory.ServiceAccount:
    """The organisation's service account, as the product builds it: the key goes nowhere
    else."""
    return directory.ServiceAccount(_key())


def _listing(account: directory.ServiceAccount, http: httpx.Client) -> directory.Directory:
    return directory.Directory(lambda scope: account.token(_admin(), (scope,)), http)


def _reading(accounts: tuple[str, ...], account: directory.ServiceAccount, keep=None):
    async def as_user(address: str) -> str:
        return await asyncio.to_thread(account.token, address, _MAIL_SCOPE)

    return loader.Reading(accounts, _MAIL, as_user, organisation=True, at_once=2, keep=keep)


def _read(accounts: tuple[str, ...], account: directory.ServiceAccount, kept: list | None = None):
    """One group read of ``accounts``: (rows per table as arrow batches, the build's notes).
    With ``kept``, the read is then told its build completed, and what it keeps is added."""

    async def keep(rows):
        assert kept is not None
        kept.append(rows)

    async def connect(_source):
        return _reading(accounts, account, None if kept is None else keep)

    load = loader.make_google_workspace_loader(connect)
    columns = {table: cm.ir_columns(table) for table in loader.MESSAGE_TABLES}
    group = load.replica_group_source(None, loader.MESSAGE_TABLES, columns)

    async def read():
        got: dict[str, list] = {table: [] for table in loader.MESSAGE_TABLES}
        async for table, batch in group.batches(1000):
            got[table].append(batch)
        if kept is not None:
            await group.committed()
        return got

    got = asyncio.run(asyncio.wait_for(read(), _READ_SECONDS))
    return got, group.notes()


def test_google_issues_a_token_to_read_as_a_user_and_as_the_administrator(account):
    """The domain has delegated the three scopes to the service account. A scope that is not
    delegated fails here by name (directory.DelegationRefused names it)."""
    assert account.token(_inside()[0], _MAIL_SCOPE)
    assert account.token(_admin(), (directory.USERS_SCOPE,))
    assert account.token(_admin(), (directory.MEMBERS_SCOPE,))
    email = json.loads(_key())["client_email"]
    print(f"service account: {email}; read as {_inside()[0]} and as the administrator")


def test_the_list_choice_names_its_mailboxes_and_the_directory_knows_them(account):
    chosen = gws.Mailboxes(gws.LIST, addresses=_inside())
    with httpx.Client() as http:
        listing = _listing(account, http)
        assert directory.mailboxes(listing, chosen) == sorted(set(_inside()))
        everyone = directory.mailboxes(listing, gws.Mailboxes(gws.EVERYONE))
    missing = sorted(set(_inside()) - set(everyone))
    assert not missing, f"not listed by the directory as users with a mailbox: {missing}"
    print(f"the directory lists {len(everyone)} user(s) with a mailbox")
    suspended = _suspended()
    if suspended is not None:
        assert suspended not in everyone, "a suspended user was listed for everyone"


def test_one_read_of_a_mailbox_feeds_the_five_tables_with_the_canonical_columns(account):
    address = _inside()[0]
    got, notes = _read((address,), account)
    for table in loader.MESSAGE_TABLES:
        wanted = [name for name, _type in cm.ir_columns(table)]
        for batch in got[table]:
            assert batch.schema.names == wanted, f"{table}: columns differ from the canonical ones"
            rows = batch.to_pylist()
            assert {row["account"] for row in rows} <= {address}, f"{table}: another account's rows"
            assert {row["provider"] for row in rows} <= {"google"}, f"{table}: provider"
    counts = {table: sum(b.num_rows for b in got[table]) for table in loader.MESSAGE_TABLES}
    print(f"rows read: {counts}; notes: {[(n.code, n.params) for n in notes]}")
    for table in ("messages", "message_recipients", "message_folders", "threads"):
        assert counts[table] > 0, f"{table}: no rows from a mailbox said to hold a message"
    assert counts["threads"] <= counts["messages"]
    assert not [n for n in notes if n.code == MAILBOXES_LEFT_OUT], "the test mailbox was left out"


# The suspended mailbox is optional: the test exists only when one is named. It is not a skip,
# which in this lane would be reported as a credential that was not supplied.
if os.environ.get("GWS_TEST_MAILBOX_SUSPENDED", "").strip():

    def test_a_suspended_user_named_in_a_list_is_left_out_and_named(account):
        """What Google answers for a suspended user is not stated on its pages; this is where
        it is seen. The reader leaves out a mailbox Google will not let be read at all."""
        suspended = _suspended()
        assert suspended is not None
        inside = _inside()[0]
        got, notes = _read(tuple(sorted({inside, suspended})), account)
        left_out = [n for n in notes if n.code == MAILBOXES_LEFT_OUT]
        assert len(left_out) == 1, f"notes were {[n.code for n in notes]}"
        assert left_out[0].params["accounts"] == [suspended] and left_out[0].params["count"] == 1
        accounts = {row["account"] for b in got["messages"] for row in b.to_pylist()}
        assert accounts == {inside}


def test_a_completed_read_keeps_each_history_id_and_nothing_has_changed_right_after(account):
    """The history id is taken when a mailbox's read begins and kept when the build completed;
    asked at once (a quiet test mailbox), the check gives the same token twice."""
    address = _inside()[0]
    kept: list[dict] = []
    _read((address,), account, kept)
    (rows,) = kept
    assert set(rows) == {(address, "", PROBE)}
    assert rows[(address, "", PROBE)].isdigit(), "what was kept is not a history id"

    async def connect(_source):
        return _reading((address,), account)

    async def asked_twice():
        source = type("Source", (), {"id": "live"})()
        return await loader.mailbox_token(connect, source), await loader.mailbox_token(
            connect, source
        )

    first, second = asyncio.run(asked_twice())
    assert first is not None, "the mailbox could not be asked whether it changed"
    assert first == second, "a quiet mailbox gave two different tokens"


def test_no_key_or_token_is_logged_or_printed(account, caplog, capsys):
    private_key = json.loads(_key())["private_key"]
    access = account.token(_inside()[0], _MAIL_SCOPE)
    with caplog.at_level(logging.DEBUG):
        addresses = tuple(sorted({_inside()[0], *([_suspended()] if _suspended() else [])}))
        _read(addresses, account)
        with httpx.Client() as http:
            directory.mailboxes(_listing(account, http), gws.Mailboxes(gws.EVERYONE))
    shown = capsys.readouterr()
    said = caplog.text + shown.out + shown.err + repr(account)
    # Each named on its own, with nothing of it in the message.
    assert private_key not in said, "the service account's key is in a log line or printed output"
    assert access not in said, "an access token is in a log line or in printed output"
