# Copyright (c) 2026 Kenneth Stott
# Canary: 7c5727bc-d180-423b-bffa-c8a3d472ff12
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Google Workspace source of the organisation's mailboxes (REQ-1923): the service account
its domain has delegated to, the directory's listing, many mailboxes read at once, the ones
left out, and what a completed read keeps. Google is a stand-in; every key and token is made
up, and none may appear in a message."""

# Requirements: REQ-1923
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

from provisa.api.errors import ApiError
from provisa.api_source.oauth_grants import CredentialRefused
from provisa.core import canonical_mail as cm
from provisa.core.mail_platforms import MailPlatformRefused
from provisa.google_workspace import SOURCE_TYPE, directory, loader
from provisa.google_workspace.gmail import GmailRefused, GmailUnavailable, QuotaExhausted
from provisa.google_workspace.settings import MailSettings, Mailboxes
from tests.unit.test_google_workspace_loader import MAILBOX, FakeGmail
from tests.unit.test_mail_platforms import _put, plane  # noqa: F401  (plane is a fixture)

KEY = '{"private_key": "made-up-private-key", "client_email": "sa@p.iam.test"}'
ADMIN = "admin@example.test"
FULL = MailSettings("full", None, (), None, False)
ORG_SOURCE = SimpleNamespace(
    id="org-mail",
    mapping={"resources": ["mail"], "mail_content": "full", "mailboxes": {"everyone": True}},
)
ENTRY = {
    "organisation_mailboxes": True,
    "organisation_key": KEY,
    "settings": {"admin_address": ADMIN},
}


# ---------------------------------------------------------------------- the service account


def _refusing(reason: str):
    def grant(_auth):
        raise CredentialRefused("Service account sa@p.iam.test reading as x", reason)

    return grant


def test_a_token_is_asked_for_to_read_as_one_user_under_the_scopes_given():
    asked = []

    def grant(auth):
        asked.append((auth.key, auth.subject, tuple(auth.scopes)))
        return "made-up-access-token"

    account = directory.ServiceAccount(KEY, grant=grant)
    assert account.token("ada@example.test", (directory.USERS_SCOPE,)) == "made-up-access-token"
    assert asked == [(KEY, "ada@example.test", (directory.USERS_SCOPE,))]


def test_a_scope_the_domain_has_not_delegated_is_refused_naming_it_and_where_to_add_it():
    account = directory.ServiceAccount(
        KEY,
        grant=_refusing("unauthorized_client: Client is unauthorized to retrieve access tokens"),
    )
    with pytest.raises(directory.DelegationRefused) as refused:
        account.token(ADMIN, (directory.USERS_SCOPE,))
    said = str(refused.value)
    assert directory.USERS_SCOPE in said and "Manage Domain Wide Delegation" in said
    assert "super administrator" in said and "24 hours" in said
    assert refused.value.scopes == (directory.USERS_SCOPE,)


@pytest.mark.parametrize(
    "reason", ["invalid_grant: Not a valid email", "invalid_grant: Invalid email or User ID"]
)
def test_an_address_that_is_no_user_of_the_domain_is_that_mailboxs_refusal(reason):
    account = directory.ServiceAccount(KEY, grant=_refusing(reason))
    with pytest.raises(directory.NotAUser) as refused:
        account.token("gone@example.test", ("s",))
    assert refused.value.address == "gone@example.test"


def test_any_other_refusal_stays_the_credentials_own():
    """A wrong key or a clock out of step is not a mailbox's fault and not a missing scope."""
    account = directory.ServiceAccount(
        KEY, grant=_refusing("invalid_grant: Invalid JWT Signature.")
    )
    with pytest.raises(CredentialRefused, match="Invalid JWT Signature"):
        account.token("ada@example.test", ("s",))


def test_the_key_is_never_said():
    account = directory.ServiceAccount(KEY, grant=_refusing("unauthorized_client"))
    assert repr(account) == "ServiceAccount()" and "made-up" not in str(vars(account).keys())
    for scopes, reason in (((directory.USERS_SCOPE,), "unauthorized_client"),):
        with pytest.raises(directory.DelegationRefused) as refused:
            account.token(ADMIN, scopes)
        assert "made-up-private-key" not in str(refused.value) and reason in str(refused.value)


# ------------------------------------------------------------------------------ the directory


class FakeDirectory:
    def __init__(self, *answers) -> None:
        self.answers, self.requests = list(answers), []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)


def _directory(*answers):
    fake = FakeDirectory(*answers)
    scopes: list[str] = []

    def token(scope: str) -> str:
        scopes.append(scope)
        return "made-up-admin-token"

    client = httpx.Client(transport=httpx.MockTransport(fake.handle))
    return directory.Directory(token, client), fake, scopes


def test_everyone_is_every_user_with_a_mailbox_to_its_last_page():
    listing, fake, scopes = _directory(
        {
            "users": [
                {"primaryEmail": "Bo@Example.test"},
                {"primaryEmail": "frozen@example.test", "suspended": True},
                {"primaryEmail": "visitor@example.test", "isGuestUser": True},
                {"primaryEmail": "nomail@example.test", "isMailboxSetup": False},
            ],
            "nextPageToken": "p2",
        },
        {"users": [{"primaryEmail": "ada@example.test", "isMailboxSetup": True}]},
    )
    found = directory.mailboxes(listing, Mailboxes("everyone"))
    assert found == ["ada@example.test", "bo@example.test"]
    first, second = fake.requests
    assert str(first.url).startswith("https://admin.googleapis.com/admin/directory/v1/users?")
    assert first.url.params["customer"] == "my_customer"
    assert first.url.params["query"] == "isSuspended=false"
    assert first.url.params["maxResults"] == "500"
    assert second.url.params["pageToken"] == "p2"
    assert first.headers["authorization"] == "Bearer made-up-admin-token"
    assert set(scopes) == {directory.USERS_SCOPE}


def test_a_groups_members_are_its_users_those_of_the_groups_inside_it_included():
    listing, fake, scopes = _directory(
        {
            "members": [
                {"email": "ada@example.test", "type": "USER", "status": "ACTIVE"},
                {"email": "team@example.test", "type": "GROUP"},
                {"email": "frozen@example.test", "type": "USER", "status": "SUSPENDED"},
                {"email": "out@elsewhere.test", "type": "EXTERNAL"},
                {"type": "CUSTOMER", "id": "C01"},
                {"email": "Bo@example.test", "type": "USER", "status": "ACTIVE"},
            ]
        }
    )
    found = directory.mailboxes(listing, Mailboxes("group", group="sales@example.test"))
    assert found == ["ada@example.test", "bo@example.test"]
    (request,) = fake.requests
    assert "/groups/sales%40example.test/members" in str(request.url)
    assert request.url.params["includeDerivedMembership"] == "true"
    assert scopes == [directory.MEMBERS_SCOPE]


def test_a_list_is_read_as_given_and_asks_the_directory_nothing():
    listing, fake, scopes = _directory()
    chosen = Mailboxes("list", addresses=("bo@example.test", "ada@example.test"))
    assert directory.mailboxes(listing, chosen) == ["ada@example.test", "bo@example.test"]
    assert fake.requests == [] and scopes == []
    assert directory.needed(chosen) == ()
    assert directory.needed(Mailboxes("everyone")) == (directory.USERS_SCOPE,)
    assert directory.needed(Mailboxes("group", group="g")) == (directory.MEMBERS_SCOPE,)


def test_a_directory_that_will_not_be_read_fails_by_googles_own_reason():
    refusal = httpx.Response(
        403,
        json={
            "error": {
                "message": "Not Authorized to access this resource/api",
                "errors": [{"reason": "forbidden"}],
            }
        },
    )
    listing, _fake, _scopes = _directory(refusal)
    with pytest.raises(directory.DirectoryRefused) as refused:
        directory.mailboxes(listing, Mailboxes("everyone"))
    assert refused.value.status == 403
    assert "forbidden: Not Authorized to access this resource/api" in str(refused.value)
    assert "made-up" not in str(refused.value)


# --------------------------------------------------------------- reading many mailboxes at once


class OrgGmail(FakeGmail):
    """One of the organisation's mailboxes: its history id, and what Google refuses of it."""

    boxes: dict[str, dict] = {}
    reading_now = 0
    most_at_once = 0
    made: list[tuple[str, bool]] = []

    def __init__(self, account, token, client, **kw) -> None:
        super().__init__()
        self.account = account
        self._box = OrgGmail.boxes[account]
        self._token = token
        OrgGmail.made.append((account, bool(kw.get("quota_user"))))

    async def profile(self) -> dict:
        await self._token()
        if self._box.get("refuse") is not None:
            raise self._box["refuse"]
        return {"emailAddress": self.account, "historyId": self._box["history"]}

    async def message_ids(self, mail):
        OrgGmail.reading_now += 1
        OrgGmail.most_at_once = max(OrgGmail.most_at_once, OrgGmail.reading_now)
        try:
            await asyncio.sleep(0)
            if self._box.get("fail_at_start") is not None:
                raise self._box["fail_at_start"]
            if self._box.get("fail_midway") is not None:
                yield list(MAILBOX)[:1]
                raise self._box["fail_midway"]
            yield list(MAILBOX)
        finally:
            OrgGmail.reading_now -= 1


@pytest.fixture
def org(monkeypatch):
    """A loader over three mailboxes, signed in by nothing; ``org.boxes`` says how each is."""
    OrgGmail.boxes = {
        "ada@example.test": {"history": "100"},
        "bo@example.test": {"history": "200"},
        "cy@example.test": {"history": "300"},
    }
    OrgGmail.reading_now = OrgGmail.most_at_once = 0
    OrgGmail.made = []
    monkeypatch.setattr(loader, "Gmail", OrgGmail)
    kept: list[dict] = []
    tokens: list[str] = []

    async def keep(rows) -> None:
        kept.append(dict(rows))

    async def connect(source) -> loader.Reading:
        async def token(account: str) -> str:
            tokens.append(account)
            refusal = OrgGmail.boxes[account].get("no_token")
            if refusal is not None:
                raise refusal
            return "made-up-access-token"

        return loader.Reading(
            tuple(sorted(OrgGmail.boxes)),
            FULL,
            token,
            organisation=True,
            at_once=org.at_once,
            keep=keep,
        )

    org = SimpleNamespace(
        boxes=OrgGmail.boxes,
        fetch=loader.make_google_workspace_loader(connect),
        connect=connect,
        kept=kept,
        tokens=tokens,
        at_once=2,
    )
    return org


async def _group(org, tables=("messages", "message_folders")):
    source = org.fetch.replica_group_source(
        ORG_SOURCE, tables, {table: cm.ir_columns(table) for table in tables}
    )
    rows: dict[str, int] = {}
    accounts: set[str] = set()
    async for table, batch in source.batches(1000):
        rows[table] = rows.get(table, 0) + batch.num_rows
        accounts |= set(batch.column("account").to_pylist())
    return source, rows, accounts


@pytest.mark.asyncio
async def test_every_mailboxs_rows_carry_its_account_and_each_is_read_as_its_own_user(org):
    source, rows, accounts = await _group(org)
    assert accounts == set(org.boxes)
    assert rows["messages"] == 3 * len(MAILBOX)
    assert source.notes() == []
    # Read as each user in turn, each call counted against that user's allowance.
    assert sorted(set(org.tokens)) == sorted(org.boxes)
    assert set(OrgGmail.made) == {(account, True) for account in org.boxes}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refusal",
    [
        directory.NotAUser("bo@example.test", "invalid_grant: Not a valid email"),
        GmailRefused("bo@example.test", "getProfile", 400, "failedPrecondition"),
        loader.GmailNotFound("bo@example.test", "getProfile", 404, "notFound"),
    ],
    ids=["no such user", "mail service not enabled", "no such mailbox"],
)
async def test_a_mailbox_google_will_not_let_be_read_is_left_out_and_reported(org, refusal, caplog):
    key = "no_token" if isinstance(refusal, directory.NotAUser) else "refuse"
    org.boxes["bo@example.test"][key] = refusal
    with caplog.at_level(logging.WARNING):
        source, rows, accounts = await _group(org)
    assert accounts == {"ada@example.test", "cy@example.test"}
    assert rows["messages"] == 2 * len(MAILBOX)
    (note,) = source.notes()
    assert note.code == "replication.mailboxes_left_out"
    assert note.params == {"count": 1, "accounts": ["bo@example.test"], "more": 0}
    assert "1 of 3 mailbox(es) were left out" in caplog.text


@pytest.mark.asyncio
async def test_something_not_found_inside_a_mailbox_is_not_a_mailbox_that_cannot_be_read(org):
    """Google answered the mailbox's profile, so the mailbox is there and may be read. A "not
    found" for a thing inside it, even before any row of it has arrived, is a failed read --
    never a mailbox left out as if it did not exist."""
    org.boxes["bo@example.test"]["fail_at_start"] = loader.GmailNotFound(
        "bo@example.test", "messages.list", 404, "notFound"
    )
    with pytest.raises(loader.GmailNotFound):
        await _group(org)


@pytest.mark.asyncio
async def test_when_no_mailbox_can_be_read_the_build_fails_as_the_setups_fault(org):
    for box in org.boxes.values():
        box["refuse"] = GmailRefused("x", "getProfile", 400, "failedPrecondition")
    with pytest.raises(loader.NoMailboxRead, match="none of the 3 mailboxes could be read"):
        await _group(org)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refusal",
    [
        QuotaExhausted("bo@example.test", "getProfile", 429, "rateLimitExceeded, tried 6 times"),
        QuotaExhausted("bo@example.test", "getProfile", 403, "dailyLimitExceeded"),
        GmailUnavailable("bo@example.test", "getProfile", 503, "backendError, tried 6 times"),
        GmailRefused("bo@example.test", "getProfile", 403, "forbidden"),
        directory.DelegationRefused(("gmail.readonly",), "unauthorized_client"),
    ],
    ids=["throttled", "daily allowance", "unavailable", "forbidden", "scope not delegated"],
)
async def test_throttling_the_allowance_and_the_setup_never_leave_a_mailbox_out(org, refusal):
    """They fail the read, and the previous copy stays (nothing was swapped)."""
    key = "no_token" if isinstance(refusal, directory.DelegationRefused) else "refuse"
    org.boxes["bo@example.test"][key] = refusal
    with pytest.raises(type(refusal)):
        await _group(org)


@pytest.mark.asyncio
async def test_a_refusal_after_a_mailbox_began_to_be_read_fails_the_read(org):
    org.boxes["bo@example.test"]["fail_midway"] = GmailRefused(
        "bo@example.test", "messages.list", 400, "failedPrecondition"
    )
    with pytest.raises(GmailRefused):
        await _group(org)


@pytest.mark.asyncio
@pytest.mark.parametrize("at_once", [1, 2, 3])
async def test_no_more_mailboxes_are_read_at_once_than_the_setting_allows(org, at_once):
    org.at_once = at_once
    await _group(org)
    assert 1 <= OrgGmail.most_at_once <= at_once


# ----------------------------------------------------------- what a completed read keeps


@pytest.mark.asyncio
async def test_a_completed_read_keeps_each_mailboxs_history_id_as_it_began(org):
    source, _rows, _accounts = await _group(org)
    assert org.kept == []  # nothing is kept when the read ends: only when the build completed
    await source.committed()
    assert org.kept == [
        {
            ("ada@example.test", "", "probe"): "100",
            ("bo@example.test", "", "probe"): "200",
            ("cy@example.test", "", "probe"): "300",
        }
    ]


@pytest.mark.asyncio
async def test_a_mailbox_left_out_is_kept_as_that(org):
    org.boxes["cy@example.test"]["refuse"] = GmailRefused(
        "cy", "getProfile", 400, "failedPrecondition"
    )
    source, _rows, _accounts = await _group(org)
    await source.committed()
    (kept,) = org.kept
    assert kept[("cy@example.test", "", "probe")] == "left_out"
    assert kept[("ada@example.test", "", "probe")] == "100"


@pytest.mark.asyncio
async def test_a_read_that_did_not_reach_every_mailboxs_end_keeps_nothing(org):
    org.boxes["bo@example.test"]["fail_midway"] = GmailUnavailable(
        "bo@example.test", "messages.get", 503, "backendError, tried 6 times"
    )
    source = org.fetch.replica_group_source(
        ORG_SOURCE, ("messages",), {"messages": cm.ir_columns("messages")}
    )
    with pytest.raises(GmailUnavailable):
        async for _table, _batch in source.batches(1000):
            pass
    # A failed build is never told it completed; were it, nothing would be kept either.
    await source.committed()
    assert org.kept == []


# --------------------------------------------------------------------------- the probe


def _probe(org):
    return org.fetch.freshness_probe(ORG_SOURCE, SimpleNamespace(table_name="messages"))


@pytest.mark.asyncio
async def test_mailboxes_nothing_happened_to_give_the_same_token_and_one_change_another(org):
    probe = _probe(org)
    first = await probe()
    assert first is not None and await probe() == first
    org.boxes["bo@example.test"]["history"] = "201"
    assert await probe() != first


@pytest.mark.asyncio
async def test_a_mailbox_that_stays_unreadable_changes_nothing_and_one_that_returns_does(org):
    org.boxes["cy@example.test"]["refuse"] = GmailRefused(
        "cy", "getProfile", 400, "failedPrecondition"
    )
    probe = _probe(org)
    without = await probe()
    assert without is not None and await probe() == without
    org.boxes["cy@example.test"]["refuse"] = None
    assert await probe() != without


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "refusal",
    [
        QuotaExhausted("bo@example.test", "getProfile", 429, "rateLimitExceeded, tried 6 times"),
        GmailRefused("bo@example.test", "getProfile", 403, "forbidden"),
        directory.DelegationRefused(("gmail.readonly",), "unauthorized_client"),
        httpx.ConnectError("no route"),
    ],
    ids=["throttled", "forbidden", "scope not delegated", "unreachable"],
)
async def test_what_cannot_be_told_is_never_unchanged(org, refusal, caplog):
    probe = _probe(org)
    assert await probe() is not None
    key = "no_token" if isinstance(refusal, directory.DelegationRefused) else "refuse"
    org.boxes["bo@example.test"][key] = refusal
    with caplog.at_level(logging.WARNING):
        assert await probe() is None
    assert "could not be asked whether they changed" in caplog.text


@pytest.mark.asyncio
async def test_a_source_that_names_no_mailbox_is_not_unchanged(org):
    org.boxes.clear()
    assert await _probe(org)() is None


# ------------------------------------------------------------- signing in as the organisation


@pytest.fixture
def organisation(plane, monkeypatch):  # noqa: F811  (the fixture from test_mail_platforms)
    from provisa.core import request_context, settings_registry

    listed: list[tuple] = []

    async def listed_mailboxes(account, admin, chosen):
        listed.append((repr(account), admin, chosen))
        return ["ada@example.test", "bo@example.test"]

    monkeypatch.setattr(loader, "listed_mailboxes", listed_mailboxes)
    monkeypatch.setattr(settings_registry, "value", lambda key: 5)
    token = request_context.set_current_org("acme")
    state = SimpleNamespace(admin_db=plane, tenant_db=None)
    yield SimpleNamespace(plane=plane, connect=loader.make_connect(state), listed=listed)
    request_context.reset_current_org(token)


@pytest.mark.asyncio
async def test_the_key_is_read_from_the_organisations_vault_with_none_bound_by_the_caller(plane):  # noqa: F811
    """A source of the organisation's mailboxes names no secret of its own, so a replica build,
    a check for changes and a preview bind no vault for it: the reader must not rely on one."""
    from provisa.core import secrets_store
    from provisa.federation.source_vault import names_org_secret

    assert names_org_secret(ORG_SOURCE) is False
    await _put(plane, **ENTRY)
    assert secrets_store.bound_org_id() is None
    account, admin = await loader.organisation_account(plane, "acme")
    assert (account._key, admin) == (KEY, ADMIN)
    assert secrets_store.bound_org_id() is None  # bound for the read, and no longer


@pytest.mark.asyncio
async def test_a_key_the_administrator_named_by_reference_is_read_from_the_vault(plane):  # noqa: F811
    """The field holds what was typed. A reference is resolved where the key is used -- which
    is also how an entry saved before the product stopped naming secrets keeps building: its
    field holds a reference to the secret it was moved to then."""
    from provisa.core import secrets_store

    old = "mail_platform_google_workspace_organisation_key"
    await secrets_store.put(plane, "acme", old, KEY, owner_id=secrets_store.ORG_OWNER)
    await _put(plane, **{**ENTRY, "organisation_key": f"${{secret:{old}}}"})
    assert secrets_store.bound_org_id() is None
    account, _admin = await loader.organisation_account(plane, "acme")
    assert account._key == KEY


@pytest.mark.asyncio
async def test_a_key_that_cannot_be_resolved_is_refused_by_the_fields_name(plane):  # noqa: F811
    await _put(plane, **{**ENTRY, "organisation_key": "${secret:never_created}"})
    with pytest.raises(MailPlatformRefused) as raised:
        await loader.organisation_account(plane, "acme")
    assert raised.value.code == "mail_platform.credential_unresolved"
    assert raised.value.params["field"] == "organisation_key"
    assert "made-up-private-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_one_mailboxes_client_secret_is_resolved_as_its_field_holds_it(plane):  # noqa: F811
    """The client's secret as the administrator entered it: a value is used as it is, a typed
    reference is read from the vault, and no caller need have bound one. The owner's approval
    is not resolved: it is the value the state store keeps."""
    from provisa.core import mail_platforms, secrets_store
    from provisa.google_workspace.settings import parse

    one = {
        "accounts": ["ada@example.test"],
        "resources": ["mail"],
        "sign_in": "google_account",
        "mail_content": "full",
    }
    await secrets_store.put(
        plane, "acme", "typed", "from-the-vault", owner_id=secrets_store.ORG_OWNER
    )
    for entered, expected in (
        ("made-up-client-secret", "made-up-client-secret"),
        ("${secret:typed}", "from-the-vault"),
    ):
        client = await _put(plane, client_secret=entered)
        auth = parse(one).auth("ada@example.test", client, "the-kept-approval")
        assert secrets_store.bound_org_id() is None
        ready = await loader._resolved(plane, "acme", auth)
        assert (ready.client_secret, ready.refresh_token) == (expected, "the-kept-approval")
        assert (
            await mail_platforms.read(plane, "acme", "google_workspace")
        ).client_secret == entered


@pytest.mark.asyncio
async def test_a_build_reads_as_the_organisation_and_lists_its_mailboxes(organisation, monkeypatch):
    await _put(organisation.plane, **ENTRY)
    asked: list[tuple] = []

    def token(self, subject, scopes):
        asked.append((subject, scopes))
        return "made-up-access-token"

    monkeypatch.setattr(directory.ServiceAccount, "token", token)
    reading = await organisation.connect(ORG_SOURCE)
    assert reading.accounts == ("ada@example.test", "bo@example.test")
    assert (reading.organisation, reading.at_once) == (True, 5)
    assert organisation.listed == [("ServiceAccount()", ADMIN, Mailboxes("everyone"))]
    assert await reading.token("bo@example.test") == "made-up-access-token"
    assert asked == [("bo@example.test", ("https://www.googleapis.com/auth/gmail.readonly",))]


@pytest.mark.asyncio
async def test_a_build_is_refused_where_its_credential_is_asked_for_once_the_switch_is_off(
    organisation,
):
    await _put(organisation.plane, organisation_key=KEY, settings={"admin_address": ADMIN})
    with pytest.raises(MailPlatformRefused) as refused:
        await organisation.connect(ORG_SOURCE)
    assert refused.value.code == "mail_platform.organisation_mailboxes_off"
    assert organisation.listed == []


@pytest.mark.asyncio
async def test_saving_a_source_of_the_organisations_mailboxes_needs_the_switch(plane, monkeypatch):  # noqa: F811
    import json

    from provisa.api import app as app_module
    from provisa.api.admin.schema_common import google_workspace_organisation_refusal
    from provisa.core import request_context

    monkeypatch.setattr(app_module.state, "admin_db", plane, raising=False)
    token = request_context.set_current_org("acme")
    try:
        source = SimpleNamespace(
            id="org-mail", type=SOURCE_TYPE, mapping_json=json.dumps(ORG_SOURCE.mapping)
        )
        await _put(plane)
        refused = await google_workspace_organisation_refusal(source)
        assert refused is not None and refused.code == "mail_platform.organisation_mailboxes_off"
        await _put(plane, **ENTRY)
        assert await google_workspace_organisation_refusal(source) is None
        one_mailbox = SimpleNamespace(
            id="mail",
            type=SOURCE_TYPE,
            mapping_json=json.dumps(
                {
                    "accounts": ["ada@example.test"],
                    "resources": ["mail"],
                    "sign_in": "google_account",
                    "refresh_token": "${secret:t}",
                    "mail_content": "full",
                }
            ),
        )
        await _put(plane)
        assert await google_workspace_organisation_refusal(one_mailbox) is None
    finally:
        request_context.reset_current_org(token)


# ------------------------------------------------------------------------------- the Check


@pytest.fixture
def check(plane, monkeypatch):  # noqa: F811
    from contextlib import asynccontextmanager

    from provisa.api.admin import google_workspace_router as router
    from provisa.core import request_context, secrets_store

    @asynccontextmanager
    async def bound():
        yield

    outcome: dict = {"found": ["ada@example.test", "bo@example.test"], "raise": None}

    async def listed_mailboxes(account, admin, chosen):
        if outcome["raise"] is not None:
            raise outcome["raise"]
        return outcome["found"]

    monkeypatch.setattr(router, "require_capability_request", lambda request, right: None)
    monkeypatch.setattr(router, "_admin_db", lambda: plane)
    monkeypatch.setattr(router, "listed_mailboxes", listed_mailboxes)
    monkeypatch.setattr(secrets_store, "bound_to_request_org", bound)
    token = request_context.set_current_org("acme")
    yield SimpleNamespace(router=router, plane=plane, outcome=outcome)
    request_context.reset_current_org(token)


async def _checked(check, mailboxes=None):
    body = check.router.MailboxesBody(mailboxes=mailboxes or {"everyone": True})
    return await check.router.check_mailboxes(None, body)


@pytest.mark.asyncio
async def test_check_answers_how_many_mailboxes_a_choice_names(check):
    await _put(check.plane, **ENTRY)
    assert await _checked(check) == {"count": 2}


@pytest.mark.asyncio
async def test_check_is_refused_as_a_build_is(check):
    with pytest.raises(ApiError) as refused:
        await _checked(check)
    assert refused.value.code == "mail_platform.not_configured"
    await _put(check.plane)
    with pytest.raises(ApiError) as refused:
        await _checked(check)
    assert (refused.value.status_code, refused.value.code) == (
        403,
        "mail_platform.organisation_mailboxes_off",
    )


@pytest.mark.asyncio
async def test_check_refuses_a_choice_that_is_not_one(check):
    await _put(check.plane, **ENTRY)
    with pytest.raises(ApiError) as refused:
        await _checked(check, {"domain": "example.test"})
    assert refused.value.code == "google_workspace.mailboxes_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "code", "says"),
    [
        (
            directory.DelegationRefused((directory.USERS_SCOPE,), "unauthorized_client"),
            "google_workspace.scope_not_delegated",
            {"scopes": directory.USERS_SCOPE, "reason": "unauthorized_client"},
        ),
        (
            directory.NotAUser(ADMIN, "invalid_grant: Not a valid email"),
            "google_workspace.admin_not_a_user",
            {"address": ADMIN, "reason": "invalid_grant: Not a valid email"},
        ),
        (
            directory.DirectoryRefused("the list of the domain's users", 403, "forbidden: no"),
            "google_workspace.directory_refused",
            {"status": 403, "reason": "forbidden: no"},
        ),
        (
            CredentialRefused("Service account sa@p.iam.test reading as a", "invalid_grant: bad"),
            "google_workspace.credential_refused",
            None,
        ),
    ],
    ids=["scope not delegated", "administrator is no user", "directory refused", "key refused"],
)
async def test_check_says_what_the_credential_is_missing_where_google_says(
    check, raised, code, says
):
    await _put(check.plane, **ENTRY)
    check.outcome["raise"] = raised
    with pytest.raises(ApiError) as refused:
        await _checked(check)
    assert refused.value.code == code
    if says is not None:
        assert says.items() <= refused.value.params.items()
    assert "made-up" not in str(refused.value.detail) and "made-up" not in str(refused.value.params)
