# Copyright (c) 2026 Kenneth Stott
# Canary: 7eb0f484-ba36-47c5-ac91-a510abbc5d21
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""How a person approves a Google Workspace source (REQ-1923): what is particular to Google in
the sign-in every such source kind shares (``provisa.core.source_sign_in``)."""

# Requirements: REQ-1923
from __future__ import annotations

import httpx

from provisa.core.source_sign_in import SignInKind, SignInRefused, register_kind
from provisa.google_workspace import SOURCE_TYPE
from collections.abc import Mapping
from typing import Any

from provisa.google_workspace import settings as gw
from provisa.google_workspace.settings import TOKEN_URL

#: Google's authorization endpoint, as its OpenID configuration document publishes it.
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
#: REQ-1994: who approved, by Google's own account of them -- asked of every sign-in, so a
#: source that reads no mail (calendars, tasks) names its account as one that does.
PROFILE_URL = "https://openidconnect.googleapis.com/v1/userinfo"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
_TIMEOUT = 10.0


def _authorization_params(account: str) -> dict[str, str]:
    # offline: a refresh token is issued. consent: it is issued again to a person who approved
    # this client before. login_hint: the account the source names is the one offered.
    return {"access_type": "offline", "prompt": "consent", "login_hint": account}


async def _approved_account(access_token: str) -> str:
    """The account the token reads, by Google's own account of who approved it."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        answer = await client.get(PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})
    if answer.status_code != 200:
        raise SignInRefused(
            "account_unread",
            f"Google approved the sign-in and would not say whose account it is "
            f"(HTTP {answer.status_code}).",
        )
    return answer.json()["email"]


def _scopes(mapping: Mapping[str, Any]) -> list[str]:
    """What the source the form states reads, and the account's address (REQ-1994)."""
    try:
        settings = gw.parse(dict(mapping))
    except gw.InvalidGoogleWorkspaceSource as invalid:
        raise SignInRefused("settings_invalid", str(invalid)) from None
    return [*settings.scopes(), EMAIL_SCOPE]


GOOGLE = SignInKind(
    id=SOURCE_TYPE,
    authorization_endpoint=AUTHORIZATION_URL,
    token_endpoint=TOKEN_URL,
    authorization_params=_authorization_params,
    approved_account=_approved_account,
    scopes=_scopes,
)

register_kind(GOOGLE)
