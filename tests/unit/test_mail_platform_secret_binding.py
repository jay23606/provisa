# Copyright (c) 2026 Kenneth Stott
# Canary: 261df2be-c6b0-43c2-9586-8723c5b8e103
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A mail platform's credential is what its administrator entered, resolved for the
organisation that owns the entry, whoever calls (the reader of a Microsoft 365 source on a
replica build, its check for changes, a preview that builds the replica on demand).

The entry holds the text entered: the value itself, or a ``${secret:NAME}`` reference the
administrator typed. Nothing is written to a vault for it and no name is made up.

The replica build binds an organisation's vault only for a source whose own connection fields
name a secret (``federation.source_vault.org_vault``). A source of the organisation's
mailboxes names none -- its credential is the platform entry's -- so the build reached the
reader with no vault bound, and a reference in the entry could not be resolved:
"Cannot resolve ${secret:…}: no organization is bound to this context".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provisa.core import mail_platforms, secrets_store
from provisa.federation.source_vault import names_org_secret
from provisa.microsoft365 import SOURCE_TYPE, directory, loader
from tests.unit.test_mail_platforms import SECRET, _put, plane  # noqa: F401  (plane is a fixture)

pytestmark = pytest.mark.unit

TENANT = "11111111-2222-3333-4444-555555555555"
ORG_SOURCE = SimpleNamespace(
    id="mail",
    type=SOURCE_TYPE,
    host=None,
    base_url=None,
    database=None,
    username=None,
    password=None,
    path=None,
    federation_hints={},
    mapping={"resources": ["mail"], "mailboxes": {"everyone": True}},
)


@pytest.fixture
def made(monkeypatch):
    """The token source the reader builds, recorded instead of dialled."""
    seen: list[tuple] = []

    class Token:
        def __init__(self, url, client_id, client_secret, **kw):
            seen.append((url, client_id, client_secret))

        def __call__(self):
            return "access-token"

    monkeypatch.setattr(directory, "ClientToken", Token)
    return seen


async def test_a_source_of_the_organisations_mailboxes_names_no_secret_of_its_own():
    # So the replica build binds no vault for it: the reader must not rely on one.
    assert names_org_secret(ORG_SOURCE) is False


OWN = "my_m365_client_secret"  # a name the administrator chose, for a secret they created


async def _entry_naming_a_secret(control, org: str, value: str) -> None:
    """The organisation's own secret, created by its administrator, and an entry that names it."""
    await secrets_store.put(control, org, OWN, value, owner_id=secrets_store.ORG_OWNER)
    await _put(
        control,
        org=org,
        platform=SOURCE_TYPE,
        client_secret=f"${{secret:{OWN}}}",
        settings={"tenant": TENANT},
        organisation_mailboxes=True,
    )


async def _vault_names(control, org: str = "acme") -> list[str]:
    held = await secrets_store.listing(control, org, owner_id=secrets_store.ORG_OWNER)
    return sorted(secret.name for secret in held)


async def test_a_typed_value_is_kept_as_typed_and_nothing_is_put_in_the_vault(plane, made):  # noqa: F811
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    entry = await mail_platforms.require_organisation(plane, "acme", SOURCE_TYPE)
    assert entry.client_secret == SECRET  # the text entered, not a reference of the product's
    assert await _vault_names(plane) == []
    await loader.organisation_token(plane, "acme")
    assert made[-1][2] == SECRET  # used as it is: a value that is no reference


async def test_a_typed_reference_is_kept_verbatim_and_resolved_with_no_vault_bound_by_the_caller(
    plane,  # noqa: F811
    made,
):
    await _entry_naming_a_secret(plane, "acme", "the-real-secret")
    entry = await mail_platforms.require_organisation(plane, "acme", SOURCE_TYPE)
    assert entry.client_secret == f"${{secret:{OWN}}}"
    assert await _vault_names(plane) == [OWN]  # only what the administrator created
    assert secrets_store.bound_org_id() is None  # as on a replica build of this source
    await loader.organisation_token(plane, "acme")
    assert made == [
        (
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            "client-1",
            "the-real-secret",
        )
    ]
    assert secrets_store.bound_org_id() is None  # bound for the read, and no longer


async def test_a_reference_is_resolved_in_the_vault_of_the_organisation_that_owns_the_entry(
    plane,  # noqa: F811
    made,
):
    """Whichever organisation's vault the caller has bound, the entry's own is read."""
    await _entry_naming_a_secret(plane, "acme", "acmes-secret")
    await _entry_naming_a_secret(plane, "other", "the-other-orgs-secret")
    async with secrets_store.bound(plane, "other"):
        await loader.organisation_token(plane, "acme")
        assert secrets_store.bound_org_id() == "other"  # the caller's binding is put back
    assert made[-1][2] == "acmes-secret"


async def test_a_reference_that_cannot_be_resolved_is_refused_by_the_fields_name(plane):  # noqa: F811
    await _put(
        plane,
        platform=SOURCE_TYPE,
        client_secret="${secret:never_created}",
        settings={"tenant": TENANT},
        organisation_mailboxes=True,
    )
    with pytest.raises(mail_platforms.MailPlatformRefused) as refused:
        await loader.organisation_token(plane, "acme")
    assert refused.value.code == "mail_platform.credential_unresolved"
    assert refused.value.params["field"] == "client_secret"
    assert refused.value.params["platform"] == SOURCE_TYPE
    # The reference named is the administrator's own; no name of the product's appears.
    assert "never_created" in str(refused.value) and "mail_platform_" not in str(refused.value)
