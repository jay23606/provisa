# Copyright (c) 2026 Kenneth Stott
# Canary: 0c503e04-26ac-475a-9fc0-75d34f7bff77
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The mail platforms an organisation's sources sign in to (REQ-1923): entered once by the
organisation's administrator, kept per organisation with the secret in its vault, and opened by
``org_settings`` in that organisation alone. The control plane is a real SQLite file; every
credential is made up."""

# Requirements: REQ-1923
from __future__ import annotations

import pytest
import sqlalchemy as sa

from provisa.api.admin import mail_platforms_router as router
from provisa.api.errors import ApiError
from provisa.core import mail_platforms, schema_admin, secrets_store
from provisa.core.database import Database, create_engine_from_url
from provisa.core.mail_platforms import Configured, MailPlatformRefused, Platform

pytestmark = pytest.mark.asyncio

GOOGLE = "google_workspace"
TENANTED = "tenanted_platform"
SECRET = "made-up-client-secret"


class _Sealer:
    def encrypt(self, value: bytes) -> bytes:
        return b"sealed:" + value[::-1]

    def decrypt(self, blob: bytes) -> bytes:
        return blob[len(b"sealed:") :][::-1]


@pytest.fixture
def plane(tmp_path, monkeypatch):
    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'plane.db'}")
    with engine.begin() as conn:
        schema_admin.metadata.create_all(
            conn,
            tables=[
                schema_admin.orgs,
                schema_admin.org_mail_platforms,
                schema_admin.secrets_store,
                schema_admin.deployment_encryption_key,
            ],
        )
    monkeypatch.setattr(secrets_store, "_cipher", lambda *, mint: _Sealer())

    async def held(conn, *, mint):
        return None

    monkeypatch.setattr(secrets_store, "_hold_the_deployments_key", held)
    monkeypatch.setitem(mail_platforms._PLATFORMS, TENANTED, Platform(TENANTED, ("tenant",)))
    return Database(engine, name="admin")


def _stored(plane) -> list[dict]:
    with plane.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sa.select(schema_admin.org_mail_platforms))]


async def _vault(plane, org: str) -> dict[str, str]:
    return await secrets_store._decrypted(plane, org, secrets_store.ORG_OWNER)


async def _put(plane, org="acme", platform=GOOGLE, **changed):
    given = {
        "client_id": "client-1",
        "client_secret": SECRET,
        "settings": {},
        "actor": "uid-ada",
        "organisation_mailboxes": False,
    }
    given.update(changed)
    return await mail_platforms.put(plane, org, platform, **given)


class TestTheStore:
    async def test_google_workspace_is_a_platform_whose_organisation_credential_is_its_own(self):
        """Its client is entered with nothing beside it; for the organisation's mailboxes it
        takes a service account's key and the administrator address directory calls are made
        as."""
        import provisa.google_workspace  # noqa: F401

        from provisa.google_workspace import DELEGATED_SCOPES, directory, settings

        assert mail_platforms.platform(GOOGLE) == Platform(
            GOOGLE,
            organisation_settings=("admin_address",),
            organisation_key=True,
            organisation_scopes=DELEGATED_SCOPES,
        )
        # The scopes the administrator is told to authorise are the ones the reader asks for.
        assert set(DELEGATED_SCOPES) == {
            settings.MAIL_SCOPES[settings.MAIL_FULL],
            directory.USERS_SCOPE,
            directory.MEMBERS_SCOPE,
        }
        assert GOOGLE in [p.id for p in mail_platforms.platforms()]

    async def test_an_organisation_that_entered_nothing_has_nothing(self, plane):
        assert await mail_platforms.read(plane, "acme", GOOGLE) is None
        with pytest.raises(MailPlatformRefused) as raised:
            await mail_platforms.require(plane, "acme", GOOGLE)
        assert raised.value.code == "mail_platform.not_configured"
        assert raised.value.params == {"platform": GOOGLE}

    async def test_the_client_is_kept_with_its_secret_as_entered(self, plane):
        """What the administrator typed is what the entry holds: nothing is written to the
        organisation's vault for it, and no name is made up."""
        kept = await _put(plane)
        assert kept == Configured(GOOGLE, "client-1", {}, client_secret=SECRET)
        assert await mail_platforms.read(plane, "acme", GOOGLE) == kept
        (row,) = _stored(plane)
        assert row["client_secret"] == SECRET
        assert await _vault(plane, "acme") == {}

    async def test_a_reference_the_administrator_typed_is_kept_verbatim(self, plane):
        kept = await _put(plane, client_secret="${secret:my_google_client}")
        assert kept.client_secret == "${secret:my_google_client}"
        assert _stored(plane)[0]["client_secret"] == "${secret:my_google_client}"
        assert await _vault(plane, "acme") == {}  # the secret is theirs to create, by that name

    async def test_one_organisations_client_is_not_anothers(self, plane):
        await _put(plane, org="acme")
        assert await mail_platforms.read(plane, "globex", GOOGLE) is None
        await _put(plane, org="globex", client_id="client-g", client_secret="made-up-other")
        acme = await mail_platforms.read(plane, "acme", GOOGLE)
        assert (acme.client_id, acme.client_secret) == ("client-1", SECRET)
        assert (await mail_platforms.read(plane, "globex", GOOGLE)).client_secret == "made-up-other"

    async def test_a_client_is_replaced_keeping_its_secret_when_none_is_given(self, plane):
        await _put(plane)
        again = await _put(plane, client_id="client-2", client_secret=None)
        assert (again.client_id, again.client_secret) == ("client-2", SECRET)
        assert len(_stored(plane)) == 1

    async def test_a_client_is_never_kept_without_a_secret(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, client_secret=None)
        assert raised.value.code == "mail_platform.incomplete"
        assert raised.value.params == {"missing": "client_secret"}
        assert _stored(plane) == []

    async def test_a_client_needs_its_id(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, client_id="  ")
        assert raised.value.params == {"missing": "client_id"}
        assert await _vault(plane, "acme") == {}

    async def test_a_platform_takes_the_settings_it_declares_and_no_other(self, plane):
        kept = await _put(plane, platform=TENANTED, settings={"tenant": " contoso "})
        assert kept.settings == {"tenant": "contoso"}
        with pytest.raises(MailPlatformRefused) as missing:
            await _put(plane, platform=TENANTED, settings={})
        assert missing.value.params == {"missing": "tenant"}
        with pytest.raises(MailPlatformRefused) as unknown:
            await _put(plane, settings={"tenant": "contoso"})
        assert unknown.value.code == "mail_platform.unknown_setting"

    async def test_a_platform_no_source_kind_declared_is_refused(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, platform="carrier_pigeon")
        assert (raised.value.code, raised.value.status) == ("mail_platform.unknown", 404)

    async def test_forgetting_removes_only_that_organisations_client(self, plane):
        await _put(plane, org="acme")
        await _put(plane, org="globex")
        assert await mail_platforms.forget(plane, "acme", GOOGLE) is True
        assert await mail_platforms.forget(plane, "acme", GOOGLE) is False
        assert await mail_platforms.read(plane, "globex", GOOGLE) is not None


KEY = '{"made-up": "service account key"}'
ORG = {"organisation_mailboxes": True, "settings": {"admin_address": "admin@example.test"}}


class TestTheOrganisationsOwnCredential:
    async def test_allowing_organisation_sources_needs_the_key_and_the_administrator(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, organisation_mailboxes=True)
        assert raised.value.code == "mail_platform.incomplete"
        assert raised.value.params == {"missing": "admin_address, organisation_key"}
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, **ORG)
        assert raised.value.params == {"missing": "organisation_key"}
        assert await mail_platforms.read(plane, "acme", GOOGLE) is None

    async def test_the_key_is_kept_as_entered(self, plane):
        kept = await _put(plane, organisation_key=KEY, **ORG)
        assert kept.organisation_key == KEY and kept.organisation_mailboxes
        assert kept.settings == {"admin_address": "admin@example.test"}
        (row,) = _stored(plane)
        assert row["organisation_key"] == KEY
        assert await _vault(plane, "acme") == {}  # nothing is written to the vault for it

    async def test_leaving_the_key_out_keeps_the_one_entered(self, plane):
        await _put(plane, organisation_key=KEY, **ORG)
        kept = await _put(plane, client_secret=None, **ORG)
        assert kept.organisation_key == KEY

    async def test_the_key_may_be_entered_before_such_sources_are_allowed(self, plane):
        kept = await _put(plane, organisation_key=KEY)
        assert kept.organisation_key is not None and not kept.organisation_mailboxes
        with pytest.raises(MailPlatformRefused) as raised:
            await mail_platforms.require_organisation(plane, "acme", GOOGLE)
        assert raised.value.code == "mail_platform.organisation_mailboxes_off"

    async def test_it_needs_no_client_once_such_sources_are_allowed(self, plane):
        """An organisation that only reads its mailboxes creates no OAuth client."""
        kept = await _put(plane, client_id="", client_secret=None, organisation_key=KEY, **ORG)
        assert kept.client_id is None and kept.organisation_mailboxes
        (row,) = _stored(plane)
        assert row["client_id"] is None and row["client_secret"] is None
        assert "mail_platform_google_workspace_client_secret" not in await _vault(plane, "acme")
        assert await mail_platforms.require_organisation(plane, "acme", GOOGLE) == kept
        # One person's sign-in says by name what it lacks.
        with pytest.raises(MailPlatformRefused) as raised:
            await mail_platforms.require(plane, "acme", GOOGLE)
        assert raised.value.code == "mail_platform.not_configured"

    async def test_without_such_sources_allowed_an_entry_needs_its_client(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, client_id="", client_secret=None, organisation_key=KEY)
        assert raised.value.params == {"missing": "client_id, client_secret"}

    async def test_half_a_client_is_refused(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, client_id="", organisation_key=KEY, **ORG)
        assert raised.value.params == {"missing": "client_id"}
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(plane, client_secret=None, organisation_key=KEY, **ORG)
        assert raised.value.params == {"missing": "client_secret"}

    async def test_a_platform_whose_credential_is_its_client_always_needs_it(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(
                plane,
                platform=TENANTED,
                client_id="",
                client_secret=None,
                settings={"tenant": "contoso"},
                organisation_mailboxes=True,
            )
        assert raised.value.params == {"missing": "client_id, client_secret"}

    async def test_an_entry_without_a_key_names_none(self, plane):
        assert (await _put(plane)).organisation_key is None

    async def test_a_platform_with_no_credential_of_its_own_takes_none(self, plane):
        with pytest.raises(MailPlatformRefused) as raised:
            await _put(
                plane, platform=TENANTED, settings={"tenant": "contoso"}, organisation_key=KEY
            )
        assert raised.value.code == "mail_platform.unknown_setting"
        assert raised.value.params == {"setting": "organisation_key"}

    async def test_the_vault_keeps_a_secret_the_key_field_names(self, plane):
        """A reference the administrator typed is found by the vault's own reference search."""
        from provisa.core import secret_references

        with plane.engine.begin() as conn:
            schema_admin.metadata.create_all(conn)
        await _put(plane, organisation_key="${secret:my_service_account}", **ORG)
        found = await secret_references.references(
            plane, "acme", "my_service_account", environments={}
        )
        assert [(r.table, r.column) for r in found] == [("org_mail_platforms", "organisation_key")]


class TestTheAdminSurface:
    @pytest.fixture
    def wired(self, plane, monkeypatch):
        seen: dict = {"guarded": []}

        async def guard(request, org_id):
            seen["guarded"].append(org_id)
            if seen.get("refuse"):
                raise ApiError(403, "secrets.org_settings_in_org_required", "no")
            return "uid-ada"

        from provisa.api.admin import source_sign_in_router

        monkeypatch.setattr(router, "_org_guard", guard)
        monkeypatch.setattr(router, "_admin_pool", lambda: plane)
        monkeypatch.setattr(
            source_sign_in_router, "_public_address", lambda: "http://localhost:3000"
        )
        return seen

    async def test_it_is_opened_by_the_organisations_own_right_in_that_organisation(self, wired):
        await router.list_platforms(None, "acme")
        await router.put_platform(
            None,
            "acme",
            GOOGLE,
            router.PlatformBody(client_id="c", client_secret=SECRET, organisation_mailboxes=False),
        )
        await router.delete_platform(None, "acme", GOOGLE)
        assert wired["guarded"] == ["acme"] * 3

    async def test_without_it_nothing_is_read_kept_or_removed(self, wired, plane):
        await _put(plane)
        wired["refuse"] = True
        for call in (
            lambda: router.list_platforms(None, "acme"),
            lambda: router.put_platform(
                None,
                "acme",
                GOOGLE,
                router.PlatformBody(client_id="x", client_secret="y", organisation_mailboxes=False),
            ),
            lambda: router.delete_platform(None, "acme", GOOGLE),
        ):
            with pytest.raises(ApiError) as raised:
                await call()
            assert raised.value.status_code == 403
        assert (await mail_platforms.read(plane, "acme", GOOGLE)).client_id == "client-1"

    async def test_the_list_says_what_is_entered_and_gives_the_address_to_register(
        self, wired, plane
    ):
        before = await router.list_platforms(None, "acme")
        google = next(p for p in before["platforms"] if p["platform"] == GOOGLE)
        assert google == {
            "platform": GOOGLE,
            "settings_fields": [],
            "configured": False,
            "client_id": None,
            "settings": {},
            "organisation_mailboxes": False,
            "organisation_settings_fields": ["admin_address"],
            "organisation_key_field": True,
            "organisation_scopes": list(mail_platforms.platform(GOOGLE).organisation_scopes),
            "organisation_key_entered": False,
            "organisation_key": None,
        }
        assert before["redirect_address"] == "http://localhost:3000/source-sign-in.html"
        await _put(plane)
        after = await router.list_platforms(None, "acme")
        google = next(p for p in after["platforms"] if p["platform"] == GOOGLE)
        assert (google["configured"], google["client_id"]) == (True, "client-1")

    @pytest.mark.parametrize("typed", [KEY, "${secret:my_google_key}"])
    async def test_the_key_field_is_answered_as_it_was_entered(self, wired, plane, typed):
        """The form shows again what the field holds: the value, or the reference typed. The
        client's secret is not part of an answer."""
        body = router.PlatformBody(
            client_id="client-1", client_secret=SECRET, organisation_key=typed, **ORG
        )
        said = await router.put_platform(None, "acme", GOOGLE, body)
        listed = await router.list_platforms(None, "acme")
        assert said["organisation_key_entered"] is True and said["organisation_mailboxes"] is True
        assert said["settings"] == {"admin_address": "admin@example.test"}
        google = next(p for p in listed["platforms"] if p["platform"] == GOOGLE)
        assert said["organisation_key"] == google["organisation_key"] == typed
        for answer in (said, listed):
            assert SECRET not in str(answer)

    async def test_a_client_taken_off_the_entry_leaves_the_vault_as_it_is(self, wired, plane):
        """The entry's row holds its credentials; a secret the administrator created and named
        in it is theirs, and taking the client off the entry removes nothing of theirs."""
        await secrets_store.put(
            plane, "acme", "my_google_client", "x", owner_id=secrets_store.ORG_OWNER
        )
        await _put(plane, client_secret="${secret:my_google_client}", organisation_key=KEY, **ORG)
        said = await router.put_platform(
            None, "acme", GOOGLE, router.PlatformBody(client_id="", **ORG)
        )
        assert (said["configured"], said["client_id"]) == (True, None)
        assert said["organisation_key_entered"] is True
        assert _stored(plane)[0]["client_secret"] is None
        assert await _vault(plane, "acme") == {"my_google_client": "x"}

    async def test_removing_an_entry_removes_its_row_and_nothing_from_the_vault(self, wired, plane):
        await secrets_store.put(
            plane, "acme", "my_google_client", "x", owner_id=secrets_store.ORG_OWNER
        )
        await _put(plane, client_secret="${secret:my_google_client}", organisation_key=KEY, **ORG)
        assert await router.delete_platform(None, "acme", GOOGLE) == {"removed": True}
        assert await mail_platforms.read(plane, "acme", GOOGLE) is None
        assert await _vault(plane, "acme") == {"my_google_client": "x"}

    async def test_no_answer_carries_the_secret(self, wired):
        kept = await router.put_platform(
            None,
            "acme",
            GOOGLE,
            router.PlatformBody(
                client_id="client-1", client_secret=SECRET, organisation_mailboxes=False
            ),
        )
        listed = await router.list_platforms(None, "acme")
        assert SECRET not in repr(kept) and SECRET not in repr(listed)

    async def test_a_platform_with_settings_lists_them_for_the_form(self, wired):
        listed = await router.list_platforms(None, "acme")
        tenanted = next(p for p in listed["platforms"] if p["platform"] == TENANTED)
        assert tenanted["settings_fields"] == ["tenant"]

    async def test_a_refusal_keeps_its_name(self, wired):
        with pytest.raises(ApiError) as raised:
            await router.put_platform(
                None,
                "acme",
                GOOGLE,
                router.PlatformBody(client_id="c", organisation_mailboxes=False),
            )
        assert (raised.value.code, raised.value.status_code) == ("mail_platform.incomplete", 400)

    async def test_an_unset_public_address_is_said_and_does_not_hide_the_list(
        self, wired, monkeypatch
    ):
        from provisa.api.admin import source_sign_in_router

        monkeypatch.setattr(source_sign_in_router, "_public_address", lambda: None)
        listed = await router.list_platforms(None, "acme")
        assert listed["redirect_address"] is None
        assert listed["redirect_problem"] == "source_sign_in.public_address_not_set"
        assert listed["platforms"]

    async def test_the_vault_keeps_a_secret_the_client_secret_field_names(self, plane):
        """The Secrets screen's delete asks the vault's reference search, which finds the
        organisation's platform entry and no other organisation's -- for a reference the
        administrator typed into the field."""
        from provisa.core import secret_references

        with plane.engine.begin() as conn:  # the search reads every table of the plane
            schema_admin.metadata.create_all(conn)
        name = "my_google_client"
        await secrets_store.put(plane, "acme", name, "x", owner_id=secrets_store.ORG_OWNER)
        await _put(plane, org="acme", client_secret=f"${{secret:{name}}}")
        found = await secret_references.references(plane, "acme", name, environments={})
        assert [(r.table, r.column, r.id) for r in found] == [
            ("org_mail_platforms", "client_secret", ["acme", GOOGLE])
        ]
        assert await secret_references.references(plane, "globex", name, environments={}) == []
        with pytest.raises(secrets_store.SecretDeleteRefused):
            await secrets_store.remove(
                plane, "acme", name, owner_id=secrets_store.ORG_OWNER, environments={}
            )
        await mail_platforms.forget(plane, "acme", GOOGLE)
        assert await secrets_store.remove(
            plane, "acme", name, owner_id=secrets_store.ORG_OWNER, environments={}
        )

    async def test_removing_what_was_never_entered_removes_nothing(self, wired):
        assert await router.delete_platform(None, "acme", GOOGLE) == {"removed": False}
