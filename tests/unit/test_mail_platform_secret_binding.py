"""A mail platform's client secret is resolved for the organisation that owns it, whoever
calls (the reader of a Microsoft 365 source on a replica build, its check for changes, a
preview that builds the replica on demand).

The replica build binds an organisation's vault only for a source whose own connection fields
name a secret (``federation.source_vault.org_vault``). A source of the organisation's
mailboxes names none -- its credential is the platform entry's -- so the build reached the
reader with no vault bound and the secret could not be resolved:
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


async def test_the_readers_token_is_made_with_no_vault_bound_by_its_caller(plane, made):  # noqa: F811
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    assert secrets_store.bound_org_id() is None  # as on a replica build of this source
    await loader.organisation_token(plane, "acme")
    assert made == [
        (f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", "client-1", SECRET)
    ]
    assert secrets_store.bound_org_id() is None  # bound for the read, and no longer


async def test_the_secret_is_read_for_the_organisation_that_owns_the_entry(plane, made):  # noqa: F811
    """Whichever organisation's vault the caller has bound, the entry's own is read."""
    await _put(
        plane, platform=SOURCE_TYPE, settings={"tenant": TENANT}, organisation_mailboxes=True
    )
    await _put(
        plane,
        org="other",
        platform=SOURCE_TYPE,
        client_secret="the-other-orgs-secret",
        settings={"tenant": TENANT},
        organisation_mailboxes=True,
    )
    async with secrets_store.bound(plane, "other"):
        await loader.organisation_token(plane, "acme")
        assert secrets_store.bound_org_id() == "other"  # the caller's binding is put back
    assert made[-1][2] == SECRET


async def test_resolving_an_entrys_secret_needs_no_binding(plane):  # noqa: F811
    await _put(plane, platform=SOURCE_TYPE, settings={"tenant": TENANT})
    entry = await mail_platforms.require(plane, "acme", SOURCE_TYPE)
    assert await mail_platforms.resolved(plane, "acme", entry.client_secret) == SECRET
