# Copyright (c) 2026 Kenneth Stott
# Canary: 2744cba8-2af6-451e-be81-f7adca784463
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The organisation's mail platforms, as its administrator sets them (REQ-1923).

``/admin/orgs/{org_id}/mail-platforms`` is the organisation's own: it is opened by
``org_settings`` held in THAT organisation, the right its vault answers to, and by nothing above
it -- not ``platform_settings``, which governs the mail the deployment sends. An administrator
enters a platform's client once; the answer says whether one is entered and gives the address
to register with the platform, ready to copy. The client's secret goes to the organisation's
vault and is never answered.
"""

# Requirements: REQ-1923
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

import provisa.google_workspace  # noqa: F401  (declares the Google Workspace platform)
import provisa.microsoft365  # noqa: F401  (declares the Microsoft 365 platform)
from provisa.api.admin.secrets_router import _admin_pool, _org_guard
from provisa.api.errors import ApiError
from provisa.core import mail_platforms, source_sign_in
from provisa.core.mail_platforms import MailPlatformRefused
from provisa.core.source_sign_in import SignInRefused

router = APIRouter(prefix="/admin/orgs/{org_id}/mail-platforms", tags=["admin"])


class PlatformBody(BaseModel):
    client_id: str
    #: Left out to keep the secret already entered.
    client_secret: str | None = None
    settings: dict[str, str] = {}
    # Whether sources may read the organisation's mailboxes with this client's own credential:
    # stated at every save.
    organisation_mailboxes: bool
    #: The platform's own credential for the organisation's mailboxes, where it has one
    #: (Google: a service account's key, as its JSON). Left out to keep the one entered.
    organisation_key: str | None = None


def _refusal(refused: MailPlatformRefused) -> ApiError:
    return ApiError(refused.status, refused.code, str(refused), None, **refused.params)


def _redirect() -> dict:
    """The address a platform is told to return a sign-in to, or why it cannot be stated."""
    from provisa.api.admin.source_sign_in_router import _public_address

    try:
        return {"redirect_address": source_sign_in.redirect_address(_public_address())}
    except SignInRefused as refused:
        return {"redirect_address": None, "redirect_problem": refused.code}


async def _entry(org_id: str, platform: mail_platforms.Platform) -> dict:
    configured = await mail_platforms.read(_admin_pool(), org_id, platform.id)
    return {
        "platform": platform.id,
        "settings_fields": list(platform.settings),
        "configured": configured is not None,
        # None with an entry: it holds no client, and its sources read with its own credential.
        "client_id": None if configured is None else configured.client_id,
        # The client's secret as the administrator entered it -- the value, or a reference they
        # typed -- so the form shows again what it holds. Read only by who may enter it
        # (_org_guard).
        "client_secret": None if configured is None else configured.client_secret,
        "settings": {} if configured is None else configured.settings,
        "organisation_mailboxes": configured is not None and configured.organisation_mailboxes,
        # What the platform is entered with for the organisation's mailboxes.
        "organisation_settings_fields": list(platform.organisation_settings),
        "organisation_key_field": platform.organisation_key,
        "organisation_scopes": list(platform.organisation_scopes),
        "organisation_key_entered": configured is not None
        and configured.organisation_key is not None,
        # The key field as the administrator entered it -- the value, or a reference they typed
        # -- so the form shows again what it holds. Read only by who may enter it (_org_guard).
        "organisation_key": None if configured is None else configured.organisation_key,
    }


@router.get("")
async def list_platforms(request: Request, org_id: str) -> dict:
    """Every mail platform sources can sign in to, and which of them this organisation has
    entered a client for."""
    await _org_guard(request, org_id)
    return {
        **_redirect(),
        "platforms": [await _entry(org_id, p) for p in mail_platforms.platforms()],
    }


@router.put("/{platform}")
async def put_platform(request: Request, org_id: str, platform: str, body: PlatformBody) -> dict:
    """Enter or replace the organisation's client for one platform."""
    actor = await _org_guard(request, org_id)
    try:
        await mail_platforms.put(
            _admin_pool(),
            org_id,
            platform,
            client_id=body.client_id,
            client_secret=body.client_secret or None,
            settings=body.settings,
            organisation_mailboxes=body.organisation_mailboxes,
            organisation_key=body.organisation_key or None,
            actor=actor,
        )
        return await _entry(org_id, mail_platforms.platform(platform))
    except MailPlatformRefused as refused:
        raise _refusal(refused) from None


@router.delete("/{platform}")
async def delete_platform(request: Request, org_id: str, platform: str) -> dict:
    """Remove the organisation's entry for one platform. Sources already signed in keep their
    own approvals but cannot renew them until a client is entered again. A secret the
    administrator named in the entry is theirs and is not touched."""
    await _org_guard(request, org_id)
    try:
        if await mail_platforms.read(_admin_pool(), org_id, platform) is None:
            return {"removed": False}
    except MailPlatformRefused as refused:
        raise _refusal(refused) from None
    await mail_platforms.forget(_admin_pool(), org_id, platform)
    return {"removed": True}
