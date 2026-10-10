# Copyright (c) 2026 Kenneth Stott
# Canary: df797510-ffbb-4712-be5d-b7a46fb341f6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
# ruff: noqa: F811  (the `plane` fixture is imported and named as a test's argument)

"""A Microsoft 365 source of the ORGANISATION's mailboxes: the administrator's switch, the
client's own token, the mailboxes a choice names in the directory, the mailboxes read several
at once with their account on every row, and one that cannot be read left out and reported.
Graph is the stand-in of ``test_microsoft365_mail``; no secret is in any message."""

# Requirements: REQ-1923

from __future__ import annotations

import asyncio
import json
import logging
import threading
from types import SimpleNamespace

import httpx
import pytest

from provisa.api.errors import ApiError
from provisa.api_source.oauth_grants import CredentialRefused
from provisa.core import canonical_mail as cm
from provisa.core import mail_platforms
from provisa.core.mail_platforms import MailPlatformRefused
from provisa.microsoft365 import SOURCE_TYPE, directory, loader, settings
from provisa.microsoft365.graph import Answer, Graph, GraphRefused, GraphThrottled
from provisa.microsoft365.settings import InvalidMicrosoft365Source, Mailboxes, parse
from tests.unit.test_mail_platforms import SECRET, _put, plane  # noqa: F401  (plane is a fixture)
from tests.unit.test_microsoft365_mail import FakeGraph, _html, _message

TENANT = "0a1b2c3d-1111-2222-3333-444455556666"
ORG = {"resources": ["mail"], "mailboxes": {"everyone": True}}


def _graph(table: dict, **kw) -> tuple[Graph, FakeGraph]:
    fake = FakeGraph(table)
    return Graph(fake.send, lambda: "access-token", sleep=lambda s: None, **kw), fake


# -------------------------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ({"everyone": True}, Mailboxes("everyone")),
        ({"group": "sales@contoso.com"}, Mailboxes("group", group="sales@contoso.com")),
        ({"group": TENANT}, Mailboxes("group", group=TENANT)),
        (
            {"list": ["B@contoso.com", "a@contoso.com", "b@contoso.com"]},
            Mailboxes("list", addresses=("b@contoso.com", "a@contoso.com")),
        ),
    ],
)
def test_a_source_of_the_organisations_mailboxes_says_which(stated, expected):
    read = parse({"resources": ["mail"], "mailboxes": stated})
    assert read.organisation and read.mailboxes == expected
    assert read.account is None and read.refresh_token is None


@pytest.mark.parametrize(
    ("mapping", "says"),
    [
        ({"mailboxes": {}}, "one of: everyone, a group, or a list"),
        ({"mailboxes": {"everyone": True, "group": "g"}}, "one of: everyone"),
        ({"mailboxes": {"everyone": False}}, "stated as true"),
        ({"mailboxes": {"group": ""}}, "names one group"),
        ({"mailboxes": {"group": "x' or 1 eq 1"}}, "names one group"),
        ({"mailboxes": {"list": []}}, "at least one address"),
        ({"mailboxes": {"list": ["not an address"]}}, "not a mailbox address"),
        ({"mailboxes": {"domain": "contoso.com"}}, "not a way to choose"),
        ({"mailboxes": {"everyone": True}, "accounts": ["a@b.co"]}, "states no accounts"),
        ({"mailboxes": {"everyone": True}, "refresh_token": "${secret:t}"}, "nobody connects it"),
        ({"mailboxes": {"everyone": True}, "resources": ["calendar"]}, "cannot read calendar"),
    ],
)
def test_a_choice_of_mailboxes_that_cannot_be_one_is_refused_by_name(mapping, says):
    with pytest.raises(InvalidMicrosoft365Source, match=says):
        parse({"resources": ["mail"], **mapping})


# ------------------------------------------------------------------------------ the switch


async def test_the_switch_is_off_until_the_administrator_turns_it_on(plane):
    await _put(plane, platform=SOURCE_TYPE, settings={"tenant": TENANT})
    kept = await mail_platforms.read(plane, "acme", SOURCE_TYPE)
    assert kept.organisation_mailboxes is False
    with pytest.raises(MailPlatformRefused) as refused:
        await mail_platforms.require_organisation(plane, "acme", SOURCE_TYPE)
    assert refused.value.code == "mail_platform.organisation_mailboxes_off"
    assert refused.value.status == 403 and refused.value.params == {"platform": SOURCE_TYPE}

    on = await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    assert on.organisation_mailboxes is True
    allowed = await mail_platforms.require_organisation(plane, "acme", SOURCE_TYPE)
    assert allowed.client_id == "client-1"


async def test_the_switch_is_stated_at_every_save(plane):
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    off = await _put(
        plane,
        platform=SOURCE_TYPE,
        client_id="client-2",
        settings={"tenant": TENANT},
        organisation_mailboxes=False,
    )
    assert off.client_id == "client-2" and off.organisation_mailboxes is False
    with pytest.raises(TypeError, match="organisation_mailboxes"):
        await mail_platforms.put(
            plane, "acme", SOURCE_TYPE, client_id="c", client_secret=None, settings={}, actor=None
        )


async def test_an_organisation_with_no_client_is_refused_as_not_configured(plane):
    with pytest.raises(MailPlatformRefused) as refused:
        await mail_platforms.require_organisation(plane, "acme", SOURCE_TYPE)
    assert refused.value.code == "mail_platform.not_configured"


async def test_one_organisations_switch_is_not_anothers(plane):
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    await _put(plane, org="other", platform=SOURCE_TYPE, settings={"tenant": TENANT})
    with pytest.raises(MailPlatformRefused):
        await mail_platforms.require_organisation(plane, "other", SOURCE_TYPE)


async def test_the_admin_route_reads_and_sets_the_switch(plane, monkeypatch):
    from provisa.api.admin import mail_platforms_router as router
    from provisa.api.admin import source_sign_in_router

    async def guard(request, org_id):
        return "uid-ada"

    monkeypatch.setattr(router, "_org_guard", guard)
    monkeypatch.setattr(router, "_admin_pool", lambda: plane)
    monkeypatch.setattr(source_sign_in_router, "_public_address", lambda: "http://localhost:3000")
    listed = await router.list_platforms(None, "acme")
    entry = next(p for p in listed["platforms"] if p["platform"] == SOURCE_TYPE)
    assert entry["organisation_mailboxes"] is False  # answered, not left out, before any client
    body = router.PlatformBody(
        client_id="c",
        client_secret=SECRET,
        settings={"tenant": TENANT},
        organisation_mailboxes=False,
    )
    entry = await router.put_platform(None, "acme", SOURCE_TYPE, body)
    assert entry["organisation_mailboxes"] is False
    body = router.PlatformBody(
        client_id="c", settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    entry = await router.put_platform(None, "acme", SOURCE_TYPE, body)
    assert entry["organisation_mailboxes"] is True
    listed = await router.list_platforms(None, "acme")
    assert SECRET not in json.dumps(listed)


async def test_saving_a_source_of_the_organisations_mailboxes_needs_the_switch(plane, monkeypatch):
    from provisa.api.admin.schema_common import microsoft_365_organisation_refusal

    monkeypatch.setattr("provisa.api.app.state", SimpleNamespace(admin_db=plane))
    monkeypatch.setattr("provisa.core.request_context.require_current_org", lambda: "acme")

    def source(mapping, type_=SOURCE_TYPE):
        return SimpleNamespace(id="m365", type=type_, mapping_json=json.dumps(mapping))

    await _put(plane, platform=SOURCE_TYPE, settings={"tenant": TENANT})
    refused = await microsoft_365_organisation_refusal(source(ORG))
    assert refused is not None and refused.code == "mail_platform.organisation_mailboxes_off"
    # A source of one mailbox, and any other source, are not asked.
    one = {"accounts": ["a@b.co"], "resources": ["mail"], "refresh_token": "${secret:t}"}
    assert await microsoft_365_organisation_refusal(source(one)) is None
    assert await microsoft_365_organisation_refusal(source({}, "postgresql")) is None
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    assert await microsoft_365_organisation_refusal(source(ORG)) is None


# --------------------------------------------------------------------- the client's token


def _token(answers):
    posts: list[tuple[str, dict]] = []

    def post(url, form):
        posts.append((url, dict(form)))
        return answers.pop(0)

    return directory.ClientToken(
        "https://login/t/token", "client-id", "the-secret", post=post
    ), posts


def test_the_token_is_the_clients_own_and_asked_for_again_only_as_it_ends():
    token, posts = _token([(200, {"access_token": "t1", "expires_in": 3600})])
    assert token() == "t1" and token() == "t1"
    (url, form) = posts[0]
    assert len(posts) == 1 and url == "https://login/t/token"
    assert form == {
        "grant_type": "client_credentials",
        "client_id": "client-id",
        "client_secret": "the-secret",
        "scope": "https://graph.microsoft.com/.default",
    }
    short, posts = _token(
        [
            (200, {"access_token": "a", "expires_in": 30}),
            (200, {"access_token": "b", "expires_in": 3600}),
        ]
    )
    assert short() == "a" and short() == "b"  # thirty seconds is inside the margin


def test_a_refused_client_fails_by_name_without_its_secret():
    token, _ = _token(
        [
            (
                401,
                {
                    "error": "invalid_client",
                    "error_description": "AADSTS7000215: Invalid client secret.",
                },
            )
        ]
    )
    with pytest.raises(CredentialRefused, match="invalid_client: AADSTS7000215") as refused:
        token()
    assert "the-secret" not in str(refused.value) and "the-secret" not in repr(token)


# --------------------------------------------------------------------------- the directory


def _user(mail, *, enabled=True, upn=None):
    return {"mail": mail, "userPrincipalName": upn or mail, "accountEnabled": enabled}


def test_everyone_is_every_enabled_user_of_the_directory_to_its_last_page():
    graph, fake = _graph(
        {
            "/users": [
                [_user("Zed@contoso.com"), _user("gone@contoso.com", enabled=False)],
                [_user(None, upn="amy@contoso.com"), _user("zed@contoso.com")],
            ]
        }
    )
    assert directory.mailboxes(graph, Mailboxes("everyone")) == [
        "amy@contoso.com",
        "zed@contoso.com",
    ]
    assert fake.calls[0][2]["$select"] == "mail,userPrincipalName,accountEnabled"
    # Members only: a guest has no mailbox in the tenant. This filter needs no advanced query.
    assert fake.calls[0][2]["$filter"] == "userType eq 'Member'"
    assert "$count" not in fake.calls[0][2] and "ConsistencyLevel" not in fake.calls[0][3]


def test_a_group_is_named_by_its_id_or_found_by_its_address():
    members = f"/groups/{TENANT}/transitiveMembers/microsoft.graph.user"
    graph, fake = _graph({members: [[_user("b@contoso.com")], [_user("a@contoso.com")]]})
    assert directory.mailboxes(graph, Mailboxes("group", group=TENANT)) == [
        "a@contoso.com",
        "b@contoso.com",
    ]
    # Narrowing a group's members to its users is an advanced query: Graph requires this
    # header and $count with it, on every page.
    first, second = fake.calls
    assert first[2]["$count"] == "true" and first[2]["$top"] == "999"
    assert first[3]["ConsistencyLevel"] == second[3]["ConsistencyLevel"] == "eventual"
    graph, fake = _graph(
        {"/groups": {"value": [{"id": TENANT}]}, members: [[_user("a@contoso.com")]]}
    )
    assert directory.mailboxes(graph, Mailboxes("group", group="sales@contoso.com")) == [
        "a@contoso.com"
    ]
    assert fake.calls[0][2]["$filter"] == "mail eq 'sales@contoso.com'"
    # A group's members are not narrowed to members of the directory: a guest in the group is
    # attempted and reported like any other.
    assert "$filter" not in fake.calls[1][2]


@pytest.mark.parametrize("found", [[], [{"id": "1"}, {"id": "2"}]])
def test_a_group_address_that_names_no_group_or_several_is_refused(found):
    graph, _ = _graph({"/groups": {"value": found}})
    with pytest.raises(directory.DirectoryRefused, match=f"names {len(found)} groups"):
        directory.mailboxes(graph, Mailboxes("group", group="sales@contoso.com"))


def test_a_list_is_read_as_given_and_asks_the_directory_nothing():
    graph, fake = _graph({})
    chosen = Mailboxes("list", addresses=("b@contoso.com", "a@contoso.com"))
    assert directory.mailboxes(graph, chosen) == ["a@contoso.com", "b@contoso.com"]
    assert fake.calls == []


def test_a_directory_the_client_may_not_read_fails_by_name():
    graph, fake = _graph({})
    fake.queued = [
        Answer(
            403,
            {},
            {
                "error": {
                    "code": "Authorization_RequestDenied",
                    "message": "Insufficient privileges",
                }
            },
        )
    ]
    with pytest.raises(GraphRefused, match="Authorization_RequestDenied"):
        directory.mailboxes(graph, Mailboxes("everyone"))


# ------------------------------------------------------------- reading several mailboxes

A, B, C = "amy@contoso.com", "bob@contoso.com", "cat@contoso.com"


def _box(address, *numbers):
    root = f"/users/{address}"
    return {
        f"{root}/messages": [[_message(n) for n in numbers]],
        **{
            f"{root}/messages/m{n}": {"body": {"contentType": "html", "content": f"<p>{n}</p>"}}
            for n in numbers
        },
    }


@pytest.fixture
def org_read(monkeypatch):
    """The loader over a stand-in Graph, signed in as the organisation with mailboxes A, B, C."""
    fake = FakeGraph({})
    monkeypatch.setattr(loader, "http_send", lambda _client: fake.send)
    seen = SimpleNamespace(
        graph=fake, accounts=(A, B, C), at_once=2, running=0, most=0, token="access-token"
    )
    guard = threading.Lock()
    send = fake.send

    def counted(method, url, params, headers, body):
        with guard:
            box = url.split("/users/")[1].split("/")[0] if "/users/" in url else None
            seen.touched = getattr(seen, "touched", set()) | ({box} if box else set())
        return send(method, url, params, headers, body)

    fake.send = counted

    async def connect(source):
        return loader.Reading(
            seen.accounts, lambda: seen.token, organisation=True, at_once=seen.at_once
        )

    seen.loader = loader.make_microsoft365_loader(connect)
    return seen


def _table(name):
    return SimpleNamespace(table_name=name)


SOURCE = SimpleNamespace(id="m365", type=SOURCE_TYPE, mapping=ORG)


def test_every_mailboxs_rows_carry_its_account(org_read):
    org_read.graph.table.update({**_box(A, 1, 2), **_box(B, 3), **_box(C, 4)})
    rows = asyncio.run(org_read.loader(SOURCE, _table("messages")))
    assert sorted((r["account"], r["id"]) for r in rows) == [
        (A, "m1"),
        (A, "m2"),
        (B, "m3"),
        (C, "m4"),
    ]
    assert {r["provider"] for r in rows} == {"microsoft"}


def test_a_group_read_gives_every_mailboxs_tables_and_no_note_when_all_are_read(org_read):
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2), **_box(C, 3)})
    tables = ("messages", "message_folders", "threads")
    columns = {t: cm.ir_columns(t) for t in tables}
    source = org_read.loader.replica_group_source(SOURCE, tables, columns)

    async def read():
        got: dict = {}
        async for table, batch in source.batches(1000):
            got.setdefault(table, []).extend(batch.to_pylist())
        return got

    got = asyncio.run(read())
    for table in tables:
        assert {r["account"] for r in got[table]} == {A, B, C}, table
    assert len(got["threads"]) == 3  # a thread is its mailbox's: one per mailbox here
    assert source.notes() == []


def test_a_mailbox_that_is_not_there_or_not_permitted_is_left_out_and_reported(org_read, caplog):
    org_read.graph.table.update({**_box(A, 1), **_box(C, 3)})  # bob's mailbox answers 404
    columns = cm.ir_columns("messages")
    source = org_read.loader.replica_source(SOURCE, _table("messages"), columns)

    async def read():
        return [r for batch in [b async for b in source.batches(1000)] for r in batch.to_pylist()]

    with caplog.at_level(logging.WARNING, logger="provisa.microsoft365.loader"):
        rows = asyncio.run(read())
    assert sorted(r["account"] for r in rows) == [A, C]
    (note,) = source.notes()
    assert note.code == "replication.mailboxes_left_out"
    assert note.params == {"count": 1, "accounts": [B], "more": 0}
    assert any(B in record.getMessage() for record in caplog.records)
    asyncio.run(read())
    assert source.notes()[0].params["count"] == 1  # a read begun again counts again, not twice


@pytest.mark.parametrize(
    ("status", "code"),
    [(403, "ErrorAccessDenied"), (404, "ErrorItemNotFound"), (400, "MailboxNotEnabledForRESTAPI")],
)
def test_what_graph_answers_for_a_mailbox_it_will_not_let_be_read(org_read, status, code):
    org_read.accounts = (A, B)
    org_read.graph.table.update(_box(A, 1))
    refusal = Answer(status, {}, {"error": {"code": code, "message": "no"}})
    send = org_read.graph.send

    def refusing(method, url, params, headers, body):
        if f"/users/{B}/" in url:
            return refusal
        return send(method, url, params, headers, body)

    org_read.graph.send = refusing
    left: list[str] = []

    async def read():
        return [
            item
            async for item in loader._read_mailboxes(
                loader.Reading((A, B), lambda: "t", organisation=True, at_once=2),
                lambda mailbox: mailbox.rows("message_folders"),
                left,
            )
        ]

    assert asyncio.run(read()) and left == [B]


def test_when_no_mailbox_can_be_read_the_build_fails_as_the_setups_fault(org_read):
    org_read.graph.queued = []
    columns = cm.ir_columns("messages")
    source = org_read.loader.replica_source(
        SOURCE, _table("messages"), columns
    )  # no mailbox answers

    async def read():
        return [b async for b in source.batches(1000)]

    with pytest.raises(loader.NoMailboxRead, match="none of the 3 mailboxes.*not been granted"):
        asyncio.run(read())


def test_throttling_never_leaves_a_mailbox_out_it_fails_the_read(org_read):
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2), **_box(C, 3)})
    send = org_read.graph.send

    def throttling(method, url, params, headers, body):
        if f"/users/{B}/" in url:
            return Answer(429, {"Retry-After": "600"}, {"error": {"code": "TooManyRequests"}})
        return send(method, url, params, headers, body)

    org_read.graph.send = throttling
    left: list[str] = []

    async def read():
        return [
            item
            async for item in loader._read_mailboxes(
                loader.Reading((A, B, C), lambda: "t", organisation=True, at_once=1),
                lambda mailbox: mailbox.rows("message_folders"),
                left,
            )
        ]

    with pytest.raises(GraphThrottled):
        asyncio.run(read())
    assert left == []


def test_a_refusal_after_a_mailbox_began_to_be_read_fails_the_read(org_read):
    root = f"/users/{A}"
    org_read.graph.table.update(
        {f"{root}/messages": [[_message(1, hasAttachments=True)]], **_html()}
    )  # the attachment listing of m1 answers 404 once its rows have begun
    left: list[str] = []

    async def read():
        return [
            item
            async for item in loader._read_mailboxes(
                loader.Reading((A,), lambda: "t", organisation=True, at_once=1),
                lambda mailbox: mailbox.message_tables(("message_folders", "attachments")),
                left,
            )
        ]

    with pytest.raises(GraphRefused):
        asyncio.run(read())
    assert left == []


def test_no_more_mailboxes_are_read_at_once_than_the_setting_allows(org_read):
    org_read.accounts = tuple(f"u{n}@contoso.com" for n in range(6))
    for account in org_read.accounts:
        org_read.graph.table.update(_box(account, 1))
    open_now: set[str] = set()
    most = 0
    guard = threading.Lock()
    original = loader.mail.Mailbox.rows

    def rows(self, table, unreadable=None):
        nonlocal most
        with guard:
            open_now.add(self.account)
            most = max(most, len(open_now))
        try:
            yield from original(self, table, unreadable)
        finally:
            with guard:
                open_now.discard(self.account)

    loader.mail.Mailbox.rows = rows
    try:
        rows_read = asyncio.run(org_read.loader(SOURCE, _table("message_folders")))
    finally:
        loader.mail.Mailbox.rows = original
    assert len(rows_read) == 6 and 1 <= most <= 2


def test_the_note_names_the_first_hundred_and_counts_the_rest():
    from provisa.federation.data_replicator import mailboxes_left_out_note

    assert mailboxes_left_out_note([]) is None
    many = [f"u{n:03}@contoso.com" for n in range(130)]
    note = mailboxes_left_out_note(many)
    assert note.params["count"] == 130 and note.params["more"] == 30
    assert note.params["accounts"] == many[:100]


# ------------------------------------------------------------------ connecting and checking


@pytest.fixture
def organisation(plane, monkeypatch):
    """An organisation whose administrator entered the client; the vault resolves its secret."""
    from provisa.core import request_context, secrets, settings_registry

    monkeypatch.setattr(request_context, "require_current_org", lambda: "acme")
    monkeypatch.setattr(secrets, "resolve_secrets", lambda value: "the-secret")
    monkeypatch.setattr(settings_registry, "value", lambda key: {"mail.mailboxes_at_once": 3}[key])
    made: list = []

    class Token:
        def __init__(self, url, client_id, client_secret, **kw):
            made.append((url, client_id, client_secret))

        def __call__(self):
            return held.token

    monkeypatch.setattr(directory, "ClientToken", Token)
    fake = FakeGraph({"/users": [[_user(B), _user(A)]]})
    monkeypatch.setattr(loader, "http_send", lambda _client: fake.send)
    held = SimpleNamespace(plane=plane, made=made, graph=fake, token="access-token")
    return held


async def test_a_build_signs_in_as_the_organisation_and_lists_its_mailboxes(organisation):
    plane = organisation.plane
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    connect = loader.make_connect(SimpleNamespace(admin_db=plane))
    reading = await connect(SimpleNamespace(id="m365", mapping=ORG))
    assert reading.organisation and reading.accounts == (A, B) and reading.at_once == 3
    assert reading.token() == "access-token"
    assert organisation.made == [
        (f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", "client-1", "the-secret")
    ]


async def test_a_build_is_refused_where_its_token_is_asked_for_once_the_switch_is_off(organisation):
    plane = organisation.plane
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    connect = loader.make_connect(SimpleNamespace(admin_db=plane))
    await connect(SimpleNamespace(id="m365", mapping=ORG))  # allowed
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=False
    )
    with pytest.raises(MailPlatformRefused) as refused:
        await connect(SimpleNamespace(id="m365", mapping=ORG))
    assert refused.value.code == "mail_platform.organisation_mailboxes_off"
    assert len(organisation.made) == 1  # no token was asked for the refused build


@pytest.fixture
def check(organisation, monkeypatch):
    from contextlib import asynccontextmanager

    from provisa.api.admin import microsoft365_router as router

    @asynccontextmanager
    async def bound():
        yield

    allowed = {"may": True}

    def require(request, capability):
        assert capability == "source_registration"
        if not allowed["may"]:
            raise ApiError(403, "auth.capability_required", "no")

    monkeypatch.setattr(router, "require_capability_request", require)
    monkeypatch.setattr(router, "_admin_db", lambda: organisation.plane)
    monkeypatch.setattr("provisa.core.secrets_store.bound_to_request_org", bound)
    organisation.router, organisation.allowed = router, allowed
    return organisation


async def test_check_answers_how_many_mailboxes_a_choice_names(check):
    await _put(
        check.plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    body = check.router.MailboxesBody(mailboxes={"everyone": True})
    assert await check.router.check_mailboxes(None, body) == {"count": 2}
    listed = check.router.MailboxesBody(mailboxes={"list": ["a@contoso.com"]})
    assert await check.router.check_mailboxes(None, listed) == {"count": 1}


async def test_check_is_refused_as_a_build_is(check):
    body = check.router.MailboxesBody(mailboxes={"everyone": True})
    with pytest.raises(ApiError) as none:
        await check.router.check_mailboxes(None, body)
    assert none.value.code == "mail_platform.not_configured"
    await _put(check.plane, platform=SOURCE_TYPE, settings={"tenant": TENANT})
    with pytest.raises(ApiError) as off:
        await check.router.check_mailboxes(None, body)
    assert (off.value.status_code, off.value.code) == (
        403,
        "mail_platform.organisation_mailboxes_off",
    )
    check.allowed["may"] = False
    with pytest.raises(ApiError) as not_allowed:
        await check.router.check_mailboxes(None, body)
    assert not_allowed.value.status_code == 403
    assert check.made == []  # nothing was asked of Microsoft for any of them


async def test_check_refuses_a_choice_that_is_not_one_and_a_directory_it_may_not_read(check):
    await _put(
        check.plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    with pytest.raises(ApiError) as invalid:
        await check.router.check_mailboxes(
            None, check.router.MailboxesBody(mailboxes={"domain": "x"})
        )
    assert (invalid.value.status_code, invalid.value.code) == (
        400,
        "microsoft_365.mailboxes_invalid",
    )
    check.graph.queued = [
        Answer(
            403, {}, {"error": {"code": "Authorization_RequestDenied", "message": "Insufficient"}}
        )
    ]
    with pytest.raises(ApiError) as denied:
        await check.router.check_mailboxes(
            None, check.router.MailboxesBody(mailboxes={"everyone": True})
        )
    assert denied.value.code == "microsoft_365.directory_refused"
    assert denied.value.params == {"status": 403, "reason": "Authorization_RequestDenied"}
    assert "the-secret" not in str(denied.value.detail) and "access-token" not in str(
        denied.value.detail
    )


async def test_the_form_is_told_whether_the_organisation_shape_is_allowed(check, monkeypatch):
    from provisa.api.admin import source_sign_in_router as sign_in

    monkeypatch.setattr(sign_in, "require_capability_request", lambda request, capability: None)
    monkeypatch.setattr(sign_in, "_admin_db", lambda: check.plane)
    monkeypatch.setattr(sign_in, "_holds_org_settings", lambda request: False)
    assert (await sign_in.status(None, SOURCE_TYPE))["organisation_mailboxes"] is False
    await _put(
        check.plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    answered = await sign_in.status(None, SOURCE_TYPE)
    assert answered == {
        "connected": False,  # asked of no mailbox
        "connected_at": None,
        "configured": True,
        "may_configure": False,
        "organisation_mailboxes": True,
    }


def test_mailboxes_at_once_is_a_live_operator_setting():
    from provisa.core import settings_registry

    setting = settings_registry.setting("mail.mailboxes_at_once")
    assert (setting.type, setting.effect, setting.default, setting.min) == ("int", "live", 4, 1)
    assert setting.card == "concurrency" and settings.ORGANISATION_SCOPE.endswith("/.default")


# --- a refusal says what the client's token carries ---


def _jwt(*roles: str, claim: bool = True) -> str:
    """An access token as Microsoft shapes one: its payload names the application permissions
    it carries (``roles``); a client granted none has no such claim."""
    import base64
    import json

    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    payload = {"aud": "https://graph.microsoft.com", **({"roles": list(roles)} if claim else {})}
    return f"{part({'alg': 'RS256'})}.{part(payload)}.signature-not-read"


def test_a_tokens_application_permissions_are_read_from_it():
    assert directory.carried(_jwt("Mail.Read", "User.Read.All")) == {"Mail.Read", "User.Read.All"}
    assert directory.carried(_jwt(claim=False)) == frozenset()  # granted nothing
    assert directory.carried("access-token") is None  # not a token that can be read
    assert directory.carried("a.b.c") is None


def test_what_a_listing_needs_is_set_against_what_the_token_carries():
    everyone, group = Mailboxes("everyone"), Mailboxes("group", group=TENANT)
    assert directory.needed(everyone) == ("User.Read.All",)
    # A group is named by its own permission, and its members are users, read as such.
    assert directory.needed(group) == ("GroupMember.Read.All", "User.Read.All")
    assert directory.needed(Mailboxes("list", addresses=(A,))) == ()
    held = directory.granted(_jwt("Mail.Read"), directory.needed(everyone))
    assert held == directory.Granted(("Mail.Read",), ("User.Read.All",))
    # A wider permission grants the narrower one.
    wide = directory.granted(_jwt("Directory.Read.All"), directory.needed(group))
    assert wide is not None and wide.missing == ()
    assert directory.granted("access-token", directory.needed(everyone)) is None


async def _refused_check(check, mailboxes: dict) -> ApiError:
    await _put(
        check.plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    check.graph.queued = [
        Answer(
            403, {}, {"error": {"code": "Authorization_RequestDenied", "message": "Insufficient"}}
        )
    ]
    with pytest.raises(ApiError) as denied:
        await check.router.check_mailboxes(None, check.router.MailboxesBody(mailboxes=mailboxes))
    assert check.token not in str(denied.value.detail)  # the token is never said
    return denied.value


async def test_a_refused_listing_names_the_permission_the_token_lacks(check):
    check.token = _jwt("Mail.Read")
    denied = await _refused_check(check, {"everyone": True})
    assert denied.code == "microsoft_365.directory_permission_missing"
    assert denied.params == {
        "status": 403,
        "reason": "Authorization_RequestDenied",
        "carries": "Mail.Read",
        "missing": "User.Read.All",
    }


async def test_a_refused_listing_says_when_the_token_carries_nothing(check):
    check.token = _jwt(claim=False)
    denied = await _refused_check(check, {"everyone": True})
    assert denied.code == "microsoft_365.directory_no_permissions"
    assert denied.params == {
        "status": 403,
        "reason": "Authorization_RequestDenied",
        "missing": "User.Read.All",
    }


async def test_a_refused_group_listing_names_the_groups_own_permission(check):
    check.token = _jwt("Mail.Read", "User.Read.All")
    denied = await _refused_check(check, {"group": TENANT})
    assert denied.code == "microsoft_365.directory_permission_missing"
    assert denied.params["missing"] == "GroupMember.Read.All"
    assert denied.params["carries"] == "Mail.Read, User.Read.All"


async def test_a_listing_refused_with_everything_granted_says_so(check):
    check.token = _jwt("User.Read.All")
    denied = await _refused_check(check, {"everyone": True})
    assert denied.code == "microsoft_365.directory_refused_granted"
    assert denied.params["carries"] == "User.Read.All" and "missing" not in denied.params


def _none_read(org_read) -> str:
    org_read.graph.queued = []
    source = org_read.loader.replica_source(SOURCE, _table("messages"), cm.ir_columns("messages"))

    async def read():
        return [b async for b in source.batches(1000)]

    with pytest.raises(loader.NoMailboxRead) as failed:
        asyncio.run(read())
    assert org_read.token not in str(failed.value)
    return str(failed.value)


def test_no_mailbox_read_without_mail_read_points_at_the_grant_or_the_exchange_scope(org_read):
    org_read.token = _jwt("User.Read.All")
    said = _none_read(org_read)
    assert "none of the 3 mailboxes" in said and "does not carry Mail.Read" in said
    # A client given mail through Exchange legitimately has no Mail.Read: the scope is named.
    assert "role assignment over a scope of mailboxes" in said


def test_no_mailbox_read_with_mail_read_does_not_blame_the_permission(org_read):
    org_read.token = _jwt("Mail.Read")
    said = _none_read(org_read)
    assert "carries Mail.Read" in said and "has not been granted" not in said


def test_every_locale_words_the_three_refusals_with_their_particulars():
    import json
    import re
    from pathlib import Path

    locales = Path(__file__).parents[2] / "provisa-ui/src/i18n/locales"
    wanted = {
        "directory_no_permissions": {"status", "reason", "missing"},
        "directory_permission_missing": {"status", "reason", "carries", "missing"},
        "directory_refused_granted": {"status", "reason", "carries"},
    }
    catalogs = sorted(locales.glob("*/serverErrors.json"))
    assert len(catalogs) == 13
    for catalog in catalogs:
        said = json.loads(catalog.read_text())["serverErrors"]["microsoft_365"]
        for key, particulars in wanted.items():
            assert set(re.findall(r"{{(\w+)}}", said[key])) == particulars, (catalog, key)


# --- a mailbox at its storage quota, and what a completed read of several keeps ---


def _org_group(org_read, monkeypatch, refused: dict[str, Answer]):
    """A group read of the organisation's mailboxes that keeps what it is given; mailboxes in
    ``refused`` answer every request with that refusal."""
    from provisa.microsoft365 import mail

    send = org_read.graph.send

    def refusing(method, url, params, headers, body):
        for address, refusal in refused.items():
            if f"/users/{address}/" in url:
                return refusal
        return send(method, url, params, headers, body)

    org_read.graph.send = refusing
    kept: list[dict] = []

    async def keep(rows):
        kept.append(rows)

    async def connect(source):
        return loader.Reading(
            org_read.accounts, lambda: org_read.token, organisation=True, at_once=2, keep=keep
        )

    tables = mail.MESSAGE_TABLES
    source = loader.make_microsoft365_loader(connect).replica_group_source(
        SOURCE, tables, {t: cm.ir_columns(t) for t in tables}
    )

    async def build():
        async for _table, _batch in source.batches(1000):
            pass
        await source.committed()

    asyncio.run(build())
    return source, kept


def test_a_mailbox_at_its_storage_quota_is_left_out_with_its_own_reason(org_read, monkeypatch):
    from provisa.federation.data_replicator import MAILBOXES_AT_QUOTA, MAILBOXES_LEFT_OUT

    org_read.accounts = (A, B, C)
    org_read.graph.table.update({**_box(A, 1), **_box(C, 3)})
    full = Answer(403, {}, {"error": {"code": "ErrorQuotaExceeded", "message": "full"}})
    source, kept = _org_group(org_read, monkeypatch, {B: full})
    notes = {note.code: note.params for note in source.notes()}
    assert notes[MAILBOXES_AT_QUOTA] == {"count": 1, "accounts": [B], "more": 0}
    assert MAILBOXES_LEFT_OUT not in notes  # reported once, by its own reason
    # Links are kept for the mailboxes read; the one left out is kept as left out, so the next
    # check asks whether it can be read now.
    (rows,) = kept
    assert {account for account, _scope, kind in rows if kind == "delta"} == {A, C}
    assert rows[(B, "", "probe")] == loader.LEFT_OUT


def test_a_completed_read_of_several_mailboxes_keeps_each_ones_links(org_read, monkeypatch):
    org_read.accounts = (A, B)
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2)})
    _source, kept = _org_group(org_read, monkeypatch, {})
    (rows,) = kept
    assert {(account, scope) for account, scope, _kind in rows} == {
        (A, "f-inbox"),
        (A, ""),
        (B, "f-inbox"),
        (B, ""),
    }
    assert rows[(A, "f-inbox", "delta")] != rows[(B, "f-inbox", "delta")]


# --- has anything changed since the last completed read? ---


def _check(org_read, kept_rows: dict | None):
    async def kept():
        return dict(kept_rows or {})

    async def connect(source):
        return loader.Reading(
            org_read.accounts,
            lambda: org_read.token,
            organisation=True,
            at_once=2,
            kept=None if kept_rows is None else kept,
        )

    return asyncio.run(loader.unchanged(connect, SOURCE))


def _read_and_keep(org_read, monkeypatch, refused: dict[str, Answer] | None = None) -> dict:
    _source, kept = _org_group(org_read, monkeypatch, refused or {})
    return kept[0]


def test_nothing_changed_since_a_completed_read_says_unchanged(org_read, monkeypatch):
    org_read.accounts = (A, B)
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2)})
    rows = _read_and_keep(org_read, monkeypatch)
    before = len(org_read.graph.calls)
    assert _check(org_read, rows) == loader.UNCHANGED
    # One batch for each mailbox; no message was listed and no body read.
    asked = org_read.graph.calls[before:]
    assert [c[0] for c in asked] == ["POST", "POST"]


def test_a_change_in_one_mailbox_asks_for_a_read(org_read, monkeypatch):
    org_read.accounts = (A, B)
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2)})
    rows = _read_and_keep(org_read, monkeypatch)
    org_read.graph.since[f"/users/{B}/mailFolders/f-inbox/messages/delta"] = [{"id": "m9"}]
    assert _check(org_read, rows) is None


def test_what_cannot_be_told_is_never_unchanged(org_read, monkeypatch):
    org_read.accounts = (A, B)
    org_read.graph.table.update({**_box(A, 1), **_box(B, 2)})
    rows = _read_and_keep(org_read, monkeypatch)
    assert _check(org_read, None) is None  # nothing is kept for this source
    assert _check(org_read, {}) is None  # no read has completed yet
    org_read.accounts = (A, B, C)  # a mailbox joined the source since
    assert _check(org_read, rows) is None
    org_read.accounts = (A,)  # one left it
    assert _check(org_read, rows) is None
    org_read.accounts = (A, B)
    org_read.graph.queued = [Answer(429, {"Retry-After": "soon"}, None)]  # Graph will not answer
    assert _check(org_read, rows) is None


def test_a_mailbox_that_was_left_out_is_asked_whether_it_can_be_read_now(org_read, monkeypatch):
    org_read.accounts = (A, B)
    org_read.graph.table.update(_box(A, 1))
    gone = Answer(404, {}, {"error": {"code": "MailboxNotEnabledForRESTAPI", "message": "no"}})
    send = org_read.graph.send
    rows = _read_and_keep(org_read, monkeypatch, {B: gone})
    # Still not readable: nothing changed, and the mailbox is not taken for a new one.
    assert _check(org_read, rows) == loader.UNCHANGED
    # It can be read now (the refusing stand-in is taken away): a read is asked for.
    org_read.graph.send = send
    org_read.graph.table.update(_box(B, 2))
    assert _check(org_read, rows) is None


def test_the_loader_offers_the_check_for_the_tables_read_from_the_mailboxes(org_read):
    probe = org_read.loader.freshness_probe
    assert probe(SOURCE, _table("messages")) is not None
    assert probe(SOURCE, _table("folders")) is not None
    assert probe(SOURCE, _table("calendar_events")) is None


# --- a check that cannot be made asks for a read; it never ends the tick with nothing asked ---


@pytest.mark.parametrize(
    "failure",
    [
        MailPlatformRefused("organisation_mailboxes_off", "switched off", status=403),
        CredentialRefused("the organisation's Microsoft 365 client", "invalid_client: wrong"),
        directory.DirectoryRefused("the group names 0 groups"),
        GraphRefused(403, "Authorization_RequestDenied", "no", "/users"),
        httpx.ConnectError("no route to host"),
        RuntimeError("the vault is away"),
    ],
    ids=lambda f: type(f).__name__,
)
def test_a_sign_in_or_listing_that_fails_asks_for_a_read_and_says_why(failure, caplog):
    async def connect(source):
        raise failure

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(loader.unchanged(connect, SimpleNamespace(id="mail"))) is None
    said = caplog.text
    assert "mail" in said and "a read is asked for" in said and type(failure).__name__ in said


def test_a_failure_while_asking_graph_or_reading_what_was_kept_asks_for_a_read(
    org_read, monkeypatch
):
    org_read.accounts = (A,)
    org_read.graph.table.update(_box(A, 1))
    rows = _read_and_keep(org_read, monkeypatch)

    def unreachable(method, url, params, headers, body):
        raise httpx.ReadTimeout("timed out")

    org_read.graph.send = unreachable
    assert _check(org_read, rows) is None  # the network, not "unchanged"

    async def kept():
        raise RuntimeError("the state store is away")

    async def connect(source):
        return loader.Reading((A,), lambda: "t", organisation=True, kept=kept)

    assert asyncio.run(loader.unchanged(connect, SOURCE)) is None


def test_an_empty_page_with_more_to_come_is_not_unchanged(org_read, monkeypatch):
    org_read.accounts = (A,)
    org_read.graph.table.update(_box(A, 1))
    rows = _read_and_keep(org_read, monkeypatch)
    assert _check(org_read, rows) == loader.UNCHANGED
    path = f"/users/{A}/mailFolders/f-inbox/messages/delta"
    org_read.graph.answers[path] = {
        "value": [],
        "@odata.nextLink": f"https://graph.microsoft.com/v1.0{path}?$skiptoken=1",
    }
    assert _check(org_read, rows) is None


def test_a_completed_read_settles_the_check_of_the_tables_it_fed(org_read, monkeypatch):
    """The read just made is not asked for again by the first check after it: the tables it
    fed are recorded as having nothing to report, after what it reached is kept."""
    from provisa.microsoft365 import mail

    org_read.accounts = (A,)
    org_read.graph.table.update(_box(A, 1))
    did: list[tuple] = []

    async def keep(rows):
        did.append(("keep", len(rows)))

    async def settle(tables):
        did.append(("settle", tuple(tables)))

    async def connect(source):
        return loader.Reading(
            (A,), lambda: org_read.token, organisation=True, keep=keep, settle=settle
        )

    tables = mail.MESSAGE_TABLES
    source = loader.make_microsoft365_loader(connect).replica_group_source(
        SOURCE, tables, {t: cm.ir_columns(t) for t in tables}
    )

    async def build():
        async for _table, _batch in source.batches(1000):
            pass
        assert did == []  # nothing before the build is recorded as completed
        await source.committed()

    asyncio.run(build())
    assert did == [("keep", 2), ("settle", tuple(tables))]


async def test_settling_sets_what_each_tables_poll_node_compares_its_check_with(
    organisation, tmp_path
):
    """The real connection's ``settle`` and ``keep``/``kept``, against the org's state store:
    the node of each table fed holds "unchanged", so the check's first answer after the read
    matches it (events.injector.check_node) and asks for no second read."""
    from provisa.core.database import Database, create_engine_from_url
    from provisa.core.schema_org import mail_sync_state, node_freshness_state
    from provisa.events import queue
    from provisa.events.nodes import source_node

    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'state.db'}")
    with engine.begin() as made:
        node_freshness_state.metadata.create_all(
            made, tables=[node_freshness_state, mail_sync_state]
        )
    state_db = Database(engine, name="state")
    await _put(
        organisation.plane,
        platform=SOURCE_TYPE,
        settings={"tenant": TENANT},
        organisation_mailboxes=True,
    )
    connect = loader.make_connect(SimpleNamespace(admin_db=organisation.plane, tenant_db=state_db))
    reading = await connect(SimpleNamespace(id="m365", mapping=ORG))
    assert reading.keep is not None and reading.kept is not None and reading.settle is not None
    await reading.keep({(A, "", "delta"): "l0"})
    assert await reading.kept() == {(A, "", "delta"): "l0"}
    await reading.settle(("messages", "threads"))
    async with state_db.acquire() as conn:
        for table in ("messages", "threads"):
            node = source_node("m365", loader.SCHEMA, table)
            assert (await queue.get_node_state(conn, node))["probe_token"] == loader.UNCHANGED
        assert (
            await queue.get_node_state(conn, source_node("m365", loader.SCHEMA, "folders")) is None
        )
    await state_db.close()
    engine.dispose()
