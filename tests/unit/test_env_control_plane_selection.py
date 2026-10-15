# Copyright (c) 2026 Kenneth Stott
# Canary: 2117431a-59e8-451c-be2b-6b81e2e54907
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Who a sandbox visitor's own environment is served to, and what happens when it is gone.

A visitor is served their environment because their MEMBERSHIP IS PINNED to it (REQ-1596):
redemption writes the pin. Nothing is derived from who the caller is, so a member of the sandbox
org who holds no pin -- its own administrators, the platform administrator (REQ-1618) -- is served
what they name, prod when they name nothing.

And a pinned visitor whose environment no longer exists, or has expired, is REFUSED (REQ-1487).
Serving them the org's prod instead would hand a visitor the one environment the pin exists to keep
them out of.
"""

import hashlib

import pytest

from provisa.api.env_routing import PROD, resolve_selected_env


class _Result:
    def __init__(self, pin):
        self._pin = pin

    def fetchone(self):
        # The membership pin (REQ-1596): the environment an invitation seated this member in, or
        # None for a member of the org itself, which the platform administrator is.
        return None if self._pin is None else (self._pin,)


class _Conn:
    def __init__(self, pin):
        self._pin = pin

    async def execute_core(self, _stmt):
        return _Result(self._pin)


class _Acquire:
    def __init__(self, pin):
        self._pin = pin

    async def __aenter__(self):
        return _Conn(self._pin)

    async def __aexit__(self, *_exc):
        return False


class _AdminDb:
    def __init__(self, pin=None):
        self._pin = pin

    def acquire(self):
        return _Acquire(self._pin)


class _Identity:
    def __init__(self, user_id, roles):
        self.user_id = user_id
        self.roles = roles


ADMIN_UID = "oLuB7qGCOvZ7o8zgMSGNbiJfHJC2"
VISITOR_UID = "visitor-42"


def _ephemeral_of(user_id: str) -> str:
    return f"ephemeral_{hashlib.md5(user_id.encode(), usedforsecurity=False).hexdigest()[:8]}"


@pytest.fixture
def _env_exists(monkeypatch):
    """Every named environment exists and never expires, so the name itself is the assertion."""
    seen: list[str] = []

    async def _get_env(_admin_db, _org_id, name):
        seen.append(name)
        return {"name": name, "expires_at": None}

    async def _renew(*_a, **_kw):
        return None

    monkeypatch.setattr("provisa.core.env_store.get_env", _get_env)
    monkeypatch.setattr("provisa.core.env_store.renew_idle_expiry", _renew)
    return seen


@pytest.mark.asyncio
async def test_the_control_plane_is_served_sandbox_prod(_env_exists):
    identity = _Identity(ADMIN_UID, ["org_admin"])  # stripped set: the right is not visible here

    selected = await resolve_selected_env(
        _AdminDb(), "sandbox", identity, None, {"user_management"}
    )

    assert selected == PROD
    assert _env_exists == []  # nothing but prod was ever looked up


@pytest.mark.asyncio
async def test_a_visitor_is_still_auto_selected_into_their_own_branch(_env_exists):
    identity = _Identity(VISITOR_UID, ["sandbox"])

    selected = await resolve_selected_env(
        _AdminDb(_ephemeral_of(VISITOR_UID)),
        "sandbox",
        identity,
        None,
        {"query_development"},
    )

    assert selected == _ephemeral_of(VISITOR_UID)


@pytest.mark.asyncio
async def test_the_claim_strings_do_not_decide_it(_env_exists):
    """The pin is the only input: an identity naming the control-plane role and pinned to a
    visitor's environment is served that environment."""
    identity = _Identity(VISITOR_UID, ["platform_admin"])

    selected = await resolve_selected_env(
        _AdminDb(_ephemeral_of(VISITOR_UID)),
        "sandbox",
        identity,
        None,
        {"cross_org"},
    )

    assert selected == _ephemeral_of(VISITOR_UID)


@pytest.mark.asyncio
async def test_other_orgs_are_untouched_by_the_auto_select(_env_exists):
    identity = _Identity(VISITOR_UID, ["analyst"])

    selected = await resolve_selected_env(_AdminDb(), "acme", identity, None, {"query_development"})

    assert selected == PROD


@pytest.mark.asyncio
async def test_a_sandbox_member_with_no_pin_is_served_prod_without_a_lookup(_env_exists):
    """Nothing is derived from the caller: naming nothing is prod, for the sandbox as for any org."""
    identity = _Identity("sandbox-org-admin", ["org_admin"])

    selected = await resolve_selected_env(
        _AdminDb(), "sandbox", identity, None, {"user_management"}
    )

    assert selected == PROD
    assert _env_exists == []


@pytest.mark.asyncio
@pytest.mark.parametrize("gone", ["missing", "expired"])
async def test_a_visitor_whose_environment_is_gone_is_refused_not_served_prod(monkeypatch, gone):
    """REQ-1487: an environment that cannot be served is a refusal, never another environment."""
    from datetime import datetime, timedelta, timezone

    from provisa.api.env_routing import EnvironmentSelectionError

    async def _get_env(_admin_db, _org_id, name):
        if gone == "missing":
            return None
        return {"name": name, "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}

    monkeypatch.setattr("provisa.core.env_store.get_env", _get_env)
    identity = _Identity(VISITOR_UID, ["sandbox"])

    with pytest.raises(EnvironmentSelectionError):
        await resolve_selected_env(
            _AdminDb(_ephemeral_of(VISITOR_UID)), "sandbox", identity, None, {"query_development"}
        )
