# Copyright (c) 2026 Kenneth Stott
# Canary: 5463ca48-991d-4a8f-bce3-d377d51dbea2
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Signing a source in to its issuer by a person's approval (REQ-1923).

The control plane is a real SQLite file, so the single use of a state and its survival across
database handles are the database's doing. The issuer is a stand-in and every credential is
made up; the vault is a dict that records what was put under which name.
"""

# Requirements: REQ-1923
from __future__ import annotations

import base64
import datetime as dt
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import sqlalchemy as sa

from provisa.core import schema_admin, secrets_store, source_sign_in
from provisa.core.database import Database, create_engine_from_url
from provisa.core.source_sign_in import SignInKind, SignInRefused

pytestmark = pytest.mark.asyncio

ORG, USER, ENV = "acme", "uid-ada", "prod"
ACCOUNT = "ada@example.test"
PUBLIC = "https://acme.provisa.test"
REDIRECT = "https://cloud.provisa.test/source-sign-in.html"
# The organisation's client secret: what its administrator entered in the platform's entry
# (here a reference they typed), and what that resolves to in the organisation's vault.
ENTERED = "${secret:the_admins_own_name}"
CLIENT_SECRET = "made-up-client-secret"
CODE = "made-up-authorization-code"
ACCESS, REFRESH = "made-up-access-token", "made-up-refresh-token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SECRETS = (CLIENT_SECRET, CODE, ACCESS, REFRESH)


class _Sealer:
    """Stands in for the vault's cipher: reversible, and not the identity."""

    def encrypt(self, value: bytes) -> bytes:
        return b"sealed:" + value[::-1]

    def decrypt(self, blob: bytes) -> bytes:
        assert blob.startswith(b"sealed:")
        return blob[len(b"sealed:") :][::-1]


class Issuer:
    """The issuer's token endpoint and its account lookup."""

    def __init__(self) -> None:
        self.forms: list[dict] = []
        self.asked_at: list[str] = []
        self.answer: httpx.Response | None = None
        self.approved = ACCOUNT

    def granted(self, **changed) -> dict:
        body = {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3599}
        body.update(changed)
        return {k: v for k, v in body.items() if v is not None}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked_at.append(str(request.url))
        self.forms.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return self.answer or httpx.Response(200, json=self.granted())

    async def approved_account(self, access_token: str) -> str:
        assert access_token == ACCESS
        return self.approved


@pytest.fixture
def control_plane(tmp_path):
    def open_handle() -> Database:
        engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'plane.db'}")
        return Database(engine, name="admin")

    first = open_handle()
    with first.engine.begin() as conn:
        schema_admin.metadata.create_all(
            conn, tables=[schema_admin.orgs, schema_admin.source_sign_ins]
        )
    first.open_handle = open_handle  # type: ignore[attr-defined]
    return first


@pytest.fixture
def vault(monkeypatch):
    """What a sign-in could write on the operator's behalf: it stays empty. The organisation's
    entry is read for its client secret as entered, resolved in that organisation's vault."""
    from provisa.core import mail_platforms

    written: dict[str, str] = {}

    async def require(admin_db, org_id, platform_id):
        return mail_platforms.Configured(platform_id, "client-1", {}, client_secret=ENTERED)

    async def resolved(admin_db, org_id, platform_id, field, value):
        assert (field, value) == (mail_platforms.CLIENT_SECRET, ENTERED)
        return CLIENT_SECRET

    monkeypatch.setattr(secrets_store, "_cipher", lambda *, mint: _Sealer())
    monkeypatch.setattr(mail_platforms, "require", require)
    monkeypatch.setattr(mail_platforms, "credential", resolved)
    return written


@pytest.fixture
def issuer(monkeypatch):
    issuer = Issuer()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        source_sign_in.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(issuer.handle), **kw),
    )
    monkeypatch.setitem(
        source_sign_in.KINDS,
        "stand_in",
        SignInKind(
            id="stand_in",
            authorization_endpoint="https://issuer.test/authorize",
            token_endpoint="https://issuer.test/token",
            authorization_params=lambda account: {"login_hint": account},
            approved_account=issuer.approved_account,
        ),
    )
    return issuer


async def _start(control_plane, vault, **changed):
    given = {
        "org_id": ORG,
        "env": ENV,
        "user_id": USER,
        "source_id": "mail",
        "kind_id": "stand_in",
        "account": ACCOUNT,
        "scopes": [SCOPE],
        "client_id": "client-1",
        "public_address": PUBLIC,
    }
    given.update(changed)
    return await source_sign_in.start(control_plane, **given)


def _asked(started) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(started.authorization_url).query).items()}


async def _complete(control_plane, vault, state, **changed):
    given = {
        "org_id": ORG,
        "user_id": USER,
        "state": state,
        "code": CODE,
        "error": None,
    }
    given.update(changed)
    return await source_sign_in.complete(control_plane, **given)


def _rows(control_plane) -> list[dict]:
    with control_plane.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(sa.select(schema_admin.source_sign_ins))]


def _says_no_secret(refused: SignInRefused) -> bool:
    said = " ".join([str(refused), refused.code, *map(str, refused.params.values())])
    return not any(secret in said for secret in SECRETS)


# -- the address the issuer returns to --------------------------------------------------------


class TestRedirectAddress:
    async def test_it_is_on_the_sign_in_host_of_the_configured_public_address(self):
        assert source_sign_in.redirect_address(PUBLIC) == REDIRECT

    @pytest.mark.parametrize(
        ("configured", "address"),
        [
            ("https://cloud.provisa.test/", "https://cloud.provisa.test/source-sign-in.html"),
            ("http://localhost:3000", "http://localhost:3000/source-sign-in.html"),
            ("https://provisa.test", "https://provisa.test/source-sign-in.html"),
            ("http://10.1.2.3:8080", "http://10.1.2.3:8080/source-sign-in.html"),
        ],
    )
    async def test_a_host_that_names_no_organisation_is_used_as_configured(
        self, configured, address
    ):
        assert source_sign_in.redirect_address(configured) == address

    @pytest.mark.parametrize("unset", [None, "", "  ", "cloud.provisa.test"])
    async def test_no_public_address_is_refused_by_name(self, unset):
        with pytest.raises(SignInRefused) as raised:
            source_sign_in.redirect_address(unset)
        assert raised.value.code == "source_sign_in.public_address_not_set"


# -- starting ----------------------------------------------------------------------------------


class TestStart:
    async def test_the_issuer_is_asked_with_a_state_and_a_challenge(
        self, control_plane, vault, issuer
    ):
        started = await _start(control_plane, vault)
        asked = _asked(started)
        assert started.authorization_url.startswith("https://issuer.test/authorize?")
        assert started.expires_in == source_sign_in.STATE_LIFETIME == 600
        assert started.return_origin == "https://cloud.provisa.test"
        assert asked["response_type"] == "code"
        assert asked["client_id"] == "client-1"
        assert asked["redirect_uri"] == REDIRECT
        assert asked["scope"] == SCOPE
        assert asked["code_challenge_method"] == "S256"
        assert asked["login_hint"] == ACCOUNT
        assert len(asked["state"]) >= 43  # 32 random bytes

    async def test_each_start_has_its_own_state(self, control_plane, vault, issuer):
        first, second = [_asked(await _start(control_plane, vault))["state"] for _ in range(2)]
        assert first != second

    async def test_only_the_states_digest_is_kept_and_the_verifier_is_sealed(
        self, control_plane, vault, issuer
    ):
        asked = _asked(await _start(control_plane, vault))
        (row,) = _rows(control_plane)
        assert row["state_digest"] == hashlib.sha256(asked["state"].encode()).hexdigest()
        assert asked["state"] not in map(str, row.values())
        assert row["verifier"].startswith(b"sealed:")
        verifier = secrets_store.unseal(row["verifier"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        assert asked["code_challenge"] == challenge.rstrip(b"=").decode()
        assert verifier.encode() not in row["verifier"]

    async def test_it_is_bound_to_who_started_it_and_what_for(self, control_plane, vault, issuer):
        await _start(control_plane, vault)
        (row,) = _rows(control_plane)
        assert (row["org_id"], row["env"], row["user_id"]) == (ORG, ENV, USER)
        assert (row["source_id"], row["account"], row["scopes"]) == ("mail", ACCOUNT, SCOPE)
        assert row["used_at"] is None

    async def test_the_organisations_client_secret_is_never_recorded_with_a_sign_in(
        self, control_plane, vault, issuer
    ):
        started = await _start(control_plane, vault)
        assert vault == {}  # start writes nothing on the operator's behalf
        (row,) = _rows(control_plane)
        # Neither the secret, nor what was entered for it, nor a name for it: the entry is
        # read when the sign-in is completed.
        assert (row["client_secret_name"], row["refresh_token_name"]) == ("", "")
        assert ENTERED not in map(str, row.values())
        assert CLIENT_SECRET not in map(str, row.values())
        assert CLIENT_SECRET not in started.authorization_url

    async def test_the_redirect_address_is_the_configured_one(self, control_plane, vault, issuer):
        with pytest.raises(SignInRefused) as raised:
            await _start(control_plane, vault, public_address="")
        assert raised.value.code == "source_sign_in.public_address_not_set"
        assert vault == {} and _rows(control_plane) == []

    async def test_an_unknown_kind_is_refused(self, control_plane, vault, issuer):
        with pytest.raises(SignInRefused) as raised:
            await _start(control_plane, vault, kind_id="nobody")
        assert raised.value.code == "source_sign_in.unknown_kind"

    @pytest.mark.parametrize("missing", ["source_id", "account", "client_id"])
    async def test_a_start_without_what_it_needs_is_refused(
        self, control_plane, vault, issuer, missing
    ):
        with pytest.raises(SignInRefused) as raised:
            await _start(control_plane, vault, **{missing: ""})
        assert raised.value.code == "source_sign_in.incomplete"
        assert vault == {}


# -- completing --------------------------------------------------------------------------------


class TestComplete:
    async def test_the_code_is_exchanged_with_the_verifier_and_the_token_goes_to_the_vault(
        self, control_plane, vault, issuer
    ):
        asked = _asked(await _start(control_plane, vault))
        done = await _complete(control_plane, vault, asked["state"])
        (form,) = issuer.forms
        assert form["grant_type"] == "authorization_code"
        assert form["code"] == CODE
        assert form["client_secret"] == CLIENT_SECRET
        assert form["redirect_uri"] == REDIRECT
        sent_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(form["code_verifier"].encode()).digest()
        )
        assert sent_challenge.rstrip(b"=").decode() == asked["code_challenge"]
        # The approval the issuer gave is the answer's: the value the source's field then
        # holds. Nothing is written anywhere on the operator's behalf.
        assert vault == {}
        assert done == source_sign_in.Completed(
            source_id="mail", account=ACCOUNT, refresh_token=REFRESH
        )

    async def test_what_it_answers_carries_the_approval_and_no_other_credential(
        self, control_plane, vault, issuer
    ):
        asked = _asked(await _start(control_plane, vault))
        done = await _complete(control_plane, vault, asked["state"])
        assert done.refresh_token == REFRESH
        assert not any(secret in repr(done) for secret in (CLIENT_SECRET, CODE, ACCESS))

    async def test_a_state_is_good_once(self, control_plane, vault, issuer):
        state = _asked(await _start(control_plane, vault))["state"]
        await _complete(control_plane, vault, state)
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.state_used"
        assert len(issuer.forms) == 1

    async def test_a_state_this_deployment_did_not_issue_is_refused(
        self, control_plane, vault, issuer
    ):
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, "made-up-state")
        assert raised.value.code == "source_sign_in.unknown_state"
        assert issuer.forms == [] and vault == {}

    @pytest.mark.parametrize("caller", [{"org_id": "globex"}, {"user_id": "uid-bo"}])
    async def test_another_organisations_or_persons_state_is_refused_and_not_spent(
        self, control_plane, vault, issuer, caller
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state, **caller)
        assert raised.value.code == "source_sign_in.state_not_yours"
        assert raised.value.status == 403
        assert issuer.forms == [] and vault == {}
        assert (await _complete(control_plane, vault, state)).account == ACCOUNT

    async def test_a_state_past_its_time_is_refused(
        self, control_plane, vault, issuer, monkeypatch
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=601)
        monkeypatch.setattr(source_sign_in, "_now", lambda: later)
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.state_expired"
        assert issuer.forms == []

    async def test_a_sign_in_may_be_completed_by_another_process(
        self, control_plane, vault, issuer
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        elsewhere = control_plane.open_handle()
        assert (await _complete(elsewhere, vault, state)).account == ACCOUNT
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.state_used"

    async def test_the_issuers_refusal_at_the_approval_is_named_and_spends_the_state(
        self, control_plane, vault, issuer
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state, code=None, error="access_denied")
        assert raised.value.code == "source_sign_in.refused_by_issuer"
        assert raised.value.params == {"error": "access_denied"}
        with pytest.raises(SignInRefused) as again:
            await _complete(control_plane, vault, state)
        assert again.value.code == "source_sign_in.state_used"

    async def test_what_the_browser_says_the_issuer_said_is_not_repeated_unless_it_is_a_name(
        self, control_plane, vault, issuer
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(
                control_plane, vault, state, code=None, error="<script>made-up</script>"
            )
        assert raised.value.params == {"error": "no_code"}

    async def test_the_issuers_refusal_of_the_code_is_named_without_what_else_it_said(
        self, control_plane, vault, issuer
    ):
        issuer.answer = httpx.Response(
            400, json={"error": "invalid_grant", "error_description": f"Bad code {CODE}"}
        )
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.refused_by_issuer"
        assert raised.value.params == {"error": "invalid_grant"}
        assert _says_no_secret(raised.value)
        assert vault == {}

    async def test_an_approval_without_a_refresh_token_is_refused(
        self, control_plane, vault, issuer
    ):
        issuer.answer = httpx.Response(200, json=issuer.granted(refresh_token=None))
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.no_refresh_token"
        assert _says_no_secret(raised.value) and vault == {}

    async def test_an_approval_by_another_account_is_refused_naming_both(
        self, control_plane, vault, issuer
    ):
        issuer.approved = "Bo@Example.test"
        state = _asked(await _start(control_plane, vault))["state"]
        with pytest.raises(SignInRefused) as raised:
            await _complete(control_plane, vault, state)
        assert raised.value.code == "source_sign_in.wrong_account"
        assert raised.value.params == {"approved": "bo@example.test", "account": ACCOUNT}
        assert _says_no_secret(raised.value) and vault == {}

    async def test_the_account_is_compared_without_regard_to_case(
        self, control_plane, vault, issuer
    ):
        issuer.approved = "Ada@Example.Test"
        state = _asked(await _start(control_plane, vault))["state"]
        assert (await _complete(control_plane, vault, state)).account == ACCOUNT


class TestAnIssuerWhoseAddressesDependOnTheSource:
    """Some issuers put a tenant in their addresses; the sign-in is started with it and the
    exchange is sent where the same tenant says."""

    @pytest.fixture
    def tenanted(self, monkeypatch, issuer):
        monkeypatch.setitem(
            source_sign_in.KINDS,
            "tenanted",
            SignInKind(
                id="tenanted",
                authorization_endpoint=lambda s: f"https://issuer.test/{s['tenant']}/authorize",
                token_endpoint=lambda s: f"https://issuer.test/{s['tenant']}/token",
                authorization_params=lambda account: {},
                approved_account=issuer.approved_account,
            ),
        )

    async def test_the_operator_is_sent_to_the_tenants_address(
        self, control_plane, vault, tenanted
    ):
        started = await _start(
            control_plane, vault, kind_id="tenanted", settings={"tenant": "contoso"}
        )
        assert started.authorization_url.startswith("https://issuer.test/contoso/authorize?")
        (row,) = _rows(control_plane)
        assert row["settings"] == '{"tenant": "contoso"}'

    async def test_the_code_is_exchanged_at_the_same_tenants_address(
        self, control_plane, vault, issuer, tenanted
    ):
        started = await _start(
            control_plane, vault, kind_id="tenanted", settings={"tenant": "contoso"}
        )
        await _complete(control_plane, vault, _asked(started)["state"])
        assert issuer.asked_at == ["https://issuer.test/contoso/token"]

    async def test_an_issuer_of_one_address_needs_no_settings(self, control_plane, vault, issuer):
        await _start(control_plane, vault)
        (row,) = _rows(control_plane)
        assert row["settings"] == "{}"


class TestWhereTheRefreshTokenGoes:
    async def test_it_is_the_answers_and_nothing_is_written_for_it(
        self, control_plane, vault, issuer
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        done = await source_sign_in.complete(
            control_plane, org_id=ORG, user_id=USER, state=state, code=CODE, error=None
        )
        assert done.refresh_token == REFRESH and vault == {}


# -- sign-ins that came to nothing --------------------------------------------------------------


class TestSweep:
    """Only a sign-in's own row is swept. Nothing of the operator's is removed."""

    @pytest.fixture
    def swept(self, control_plane, vault):
        async def run() -> None:
            await source_sign_in.sweep(control_plane, org_id=ORG, env=ENV)

        return run

    @staticmethod
    def _later(monkeypatch, seconds: int) -> None:
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)
        monkeypatch.setattr(source_sign_in, "_now", lambda: later)

    async def test_a_sign_in_still_in_time_is_left_alone(self, control_plane, vault, issuer, swept):
        await _start(control_plane, vault)
        await swept()
        assert len(_rows(control_plane)) == 1

    async def test_one_never_completed_loses_its_row(
        self, control_plane, vault, issuer, swept, monkeypatch
    ):
        await _start(control_plane, vault)
        self._later(monkeypatch, 601)
        await swept()
        assert _rows(control_plane) == [] and vault == {}

    async def test_one_completed_loses_its_row_after_a_day(
        self, control_plane, vault, issuer, swept, monkeypatch
    ):
        state = _asked(await _start(control_plane, vault))["state"]
        await _complete(control_plane, vault, state)
        self._later(monkeypatch, 3600)
        await swept()
        assert len(_rows(control_plane)) == 1
        self._later(monkeypatch, 24 * 3600 + 1)
        await swept()
        assert _rows(control_plane) == [] and vault == {}

    async def test_a_source_being_signed_in_again_keeps_its_new_sign_in(
        self, control_plane, vault, issuer, swept, monkeypatch
    ):
        await _start(control_plane, vault)
        self._later(monkeypatch, 601)
        await _start(control_plane, vault)  # the operator tries again
        await swept()
        assert len(_rows(control_plane)) == 1

    async def test_another_organisations_sign_ins_are_not_touched(
        self, control_plane, vault, issuer, swept, monkeypatch
    ):
        await _start(control_plane, vault, org_id="globex")
        self._later(monkeypatch, 601)
        await swept()
        assert len(_rows(control_plane)) == 1
