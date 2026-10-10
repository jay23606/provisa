# Copyright (c) 2026 Kenneth Stott
# Canary: 32f3b87a-214a-4865-9e4e-f04e1d7c7f9b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a Google Workspace source is set up with (REQ-1923). Every credential is made up."""

from __future__ import annotations

import datetime as dt

import pytest

from provisa.core.auth_models import ApiAuthOAuth2RefreshToken
from provisa.core.mail_platforms import Configured
from provisa.google_workspace import settings as gw
from provisa.google_workspace.settings import InvalidGoogleWorkspaceSource, parse

READONLY = "https://www.googleapis.com/auth/gmail.readonly"
METADATA = "https://www.googleapis.com/auth/gmail.metadata"


def _person(**changed) -> dict:
    stated = {
        "accounts": ["ada@example.test"],
        "resources": ["mail"],
        "sign_in": "google_account",
        "refresh_token": "${secret:gw_refresh_token}",
        "mail_content": "full",
    }
    stated.update(changed)
    return {k: v for k, v in stated.items() if v is not None}


def _organisation(**changed) -> dict:
    """A source of the organisation's mailboxes: it names which, and holds no credential."""
    stated = {"resources": ["mail"], "mail_content": "full", "mailboxes": {"everyone": True}}
    stated.update(changed)
    return {k: v for k, v in stated.items() if v is not None}


def _refused(mapping: dict) -> str:
    with pytest.raises(InvalidGoogleWorkspaceSource) as raised:
        parse(mapping)
    return str(raised.value)


class TestScopes:
    def test_whole_messages_ask_for_read_only_mail_and_nothing_else(self):
        assert parse(_person()).scopes() == [READONLY]

    def test_headers_and_labels_only_asks_for_the_metadata_scope(self):
        assert parse(_person(mail_content="headers")).scopes() == [METADATA]

    def test_a_resource_not_ticked_adds_no_scope(self, monkeypatch):
        monkeypatch.setattr(gw, "RESOURCES_READ", frozenset(gw.RESOURCES))
        assert parse(_person(resources=["mail", "tasks"])).scopes() == [
            READONLY,
            "https://www.googleapis.com/auth/tasks.readonly",
        ]
        calendar_only = _person(resources=["calendar"], mail_content=None)
        assert parse(calendar_only).scopes() == [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ]

    def test_every_scope_is_read_only(self):
        every = [*gw.MAIL_SCOPES.values(), *(s for ss in gw.RESOURCE_SCOPES.values() for s in ss)]
        assert all(s.endswith((".readonly", ".metadata")) for s in every)


class TestResources:
    def test_something_must_be_ticked(self):
        assert "Choose what the source reads" in _refused(_person(resources=[]))

    def test_an_unknown_resource_is_refused_by_name(self):
        assert "drive is not something" in _refused(_person(resources=["mail", "drive"]))

    def test_a_resource_not_yet_read_is_refused_by_name(self):
        said = _refused(_person(resources=["mail", "calendar"]))
        assert said == "calendar is not read by this version"

    def test_a_mail_setting_without_mail_is_refused(self, monkeypatch):
        monkeypatch.setattr(gw, "RESOURCES_READ", frozenset(gw.RESOURCES))
        said = _refused(_person(resources=["tasks"], mail_search="from:bo@example.test"))
        assert said.startswith("mail_content, mail_search is a setting of mail")


class TestAccounts:
    def test_one_account_is_read(self):
        assert parse(_person()).accounts == ("ada@example.test",)

    def test_no_account_is_refused(self):
        assert _refused(_person(accounts=[])) == "Name the account to read"

    def test_a_second_account_is_refused_naming_both(self):
        said = _refused(_person(accounts=["ada@example.test", "bo@example.test"]))
        assert (
            said == "A source reads one account; 2 were named (ada@example.test, bo@example.test)"
        )

    @pytest.mark.parametrize(
        "account", ["ada", "ada@", "@example.test", "ada@example", "a b@x.test"]
    )
    def test_what_is_not_an_address_is_refused(self, account):
        assert "is not an email address" in _refused(_person(accounts=[account]))

    def test_the_same_account_twice_is_refused(self):
        said = _refused(_person(accounts=["ada@example.test", "ada@example.test"]))
        assert said == "accounts names ada@example.test more than once"


class TestSignIn:
    def test_a_person_signs_in_with_their_approval_of_the_organisations_client(self):
        client = Configured("google_workspace", "org-client-1", {}, client_secret="as-entered")
        auth = parse(_person()).auth("ada@example.test", client)
        assert auth == ApiAuthOAuth2RefreshToken(
            client_id="org-client-1",
            client_secret="as-entered",
            refresh_token="${secret:gw_refresh_token}",
            token_url="https://oauth2.googleapis.com/token",
        )

    def test_the_source_holds_no_client_of_its_own(self):
        said = _refused(_person(client_id="client-1", client_secret="${secret:x}"))
        assert said == "client_id, client_secret is not a setting of a Google Workspace source"

    def test_an_account_the_source_does_not_name_is_not_signed_in(self):
        client = Configured("google_workspace", "org-client-1", {})
        with pytest.raises(
            InvalidGoogleWorkspaceSource, match="bo@example.test is not the mailbox"
        ):
            parse(_person()).auth("bo@example.test", client)

    def test_a_connected_mailbox_signs_in_as_its_owner_and_no_other_way(self):
        assert "sign_in must be google_account, not None" in _refused(_person(sign_in=None))
        said = _refused(_person(sign_in="service_account"))
        assert "sign_in must be google_account, not 'service_account'" in said
        assert "the organisation's mailboxes are read by a source that states mailboxes" in said

    def test_a_person_sign_in_needs_the_approval(self):
        said = _refused(_person(refresh_token=None))
        assert said == "google_account sign-in needs refresh_token"

    def test_a_source_holds_no_service_account_key(self):
        """The key is the organisation's, on its platform entry, and nowhere else."""
        said = _refused(_person(service_account_key="${secret:k}"))
        assert said == "service_account_key is not a setting of a Google Workspace source"


class TestTheOrganisationsMailboxes:
    def test_a_source_of_everyone_names_no_account_and_holds_no_credential(self):
        settings = parse(_organisation())
        assert settings.organisation and settings.mailboxes == gw.Mailboxes("everyone")
        assert (settings.accounts, settings.refresh_token) == ((), None)
        assert settings.scopes() == [READONLY]
        assert not parse(_person()).organisation

    def test_a_group_is_named_by_its_address_or_its_id(self):
        chosen = parse(_organisation(mailboxes={"group": "sales@example.test"})).mailboxes
        assert chosen == gw.Mailboxes("group", group="sales@example.test")
        for bad in ("", "two words", "a/b", "x'y", 7):
            assert "mailboxes.group names one group" in _refused(
                _organisation(mailboxes={"group": bad})
            )

    def test_a_list_is_addresses_each_once_in_lower_case(self):
        chosen = parse(
            _organisation(
                mailboxes={"list": ["Ada@Example.test", "bo@example.test", "ada@example.test"]}
            )
        ).mailboxes
        assert chosen == gw.Mailboxes("list", addresses=("ada@example.test", "bo@example.test"))
        assert "names at least one address" in _refused(_organisation(mailboxes={"list": []}))
        assert "'ada' is not a mailbox address" in _refused(
            _organisation(mailboxes={"list": ["ada"]})
        )

    @pytest.mark.parametrize(
        "stated", [{}, {"everyone": True, "list": ["a@x.test"]}, "everyone", ["a@x.test"]]
    )
    def test_exactly_one_way_of_choosing_is_stated(self, stated):
        assert "mailboxes must say one of" in _refused(_organisation(mailboxes=stated))

    def test_everyone_is_stated_as_true_and_another_way_is_refused_by_name(self):
        assert "mailboxes.everyone is stated as true" in _refused(
            _organisation(mailboxes={"everyone": False})
        )
        assert "mailboxes.domain is not a way to choose mailboxes" in _refused(
            _organisation(mailboxes={"domain": "example.test"})
        )

    @pytest.mark.parametrize(
        "own",
        [
            {"accounts": ["ada@example.test"]},
            {"sign_in": "google_account"},
            {"refresh_token": "${secret:t}"},
        ],
    )
    def test_nobody_connects_it(self, own):
        said = _refused(_organisation(**own))
        assert "a source of the organisation's mailboxes states no" in said
        assert "nobody connects it" in said

    def test_it_states_how_much_of_each_message_like_any_source_of_mail(self):
        assert "mail_content must be one of" in _refused(_organisation(mail_content=None))
        assert parse(_organisation(mail_content="headers")).scopes() == [METADATA]


class TestMail:
    def test_what_narrows_the_mail_held(self):
        mail = parse(
            _person(
                mail_search=" from:bo@example.test ",
                mail_labels=["Clients", "Invoices"],
                mail_since="2026-01-01",
                mail_include_spam_trash=True,
            )
        ).mail
        assert mail == gw.MailSettings(
            content="full",
            search="from:bo@example.test",
            labels=("Clients", "Invoices"),
            since=dt.date(2026, 1, 1),
            include_spam_trash=True,
        )

    def test_nothing_stated_narrows_nothing(self):
        assert parse(_person()).mail == gw.MailSettings("full", None, (), None, False)

    def test_how_much_is_read_must_be_stated(self):
        assert "mail_content must be one of full, headers" in _refused(_person(mail_content=None))

    @pytest.mark.parametrize(
        "narrowing", [{"mail_search": "is:unread"}, {"mail_since": "2026-01-01"}]
    )
    def test_headers_only_takes_no_search(self, narrowing):
        said = _refused(_person(mail_content="headers", **narrowing))
        assert said.startswith("Google does not search mail read as headers and labels only")

    def test_headers_only_may_still_be_narrowed_by_label(self):
        assert parse(_person(mail_content="headers", mail_labels=["Clients"])).mail.labels == (
            "Clients",
        )

    def test_a_date_that_is_not_one_is_refused(self):
        assert "mail_since must be a date as YYYY-MM-DD" in _refused(
            _person(mail_since="last year")
        )

    def test_spam_and_trash_is_yes_or_no(self):
        said = _refused(_person(mail_include_spam_trash="yes"))
        assert said == "mail_include_spam_trash must be true or false"


def test_a_setting_that_is_not_read_is_refused_by_name():
    said = _refused(_person(password="made-up", mail_query="x"))
    assert said == "mail_query, password is not a setting of a Google Workspace source"
