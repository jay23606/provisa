# Copyright (c) 2026 Kenneth Stott
# Canary: d2a01f7e-9cdf-4470-8b2e-20403d7255aa
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the Sources form asks about a Google Workspace source of the organisation's mailboxes
(REQ-1923): how many mailboxes a choice names, before the source is saved.

One listing of the directory with the organisation's own service account, read as its
administrator. It is refused as a build of such a source is: by name when the organisation has
entered no credential, when its administrator has not allowed sources that read the
organisation's mailboxes, when the domain has not delegated the scope the listing needs (the
refusal names that scope and where it is authorised), when the administrator address is no
user of the domain, and when the directory will not be read. No key and no token is part of an
answer.
"""

# Requirements: REQ-1923
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from provisa.api.admin.capabilities import require_capability_request
from provisa.api.errors import ApiError
from provisa.api_source.caller import ApiCallError
from provisa.core.mail_platforms import MailPlatformRefused
from provisa.google_workspace import settings as gws
from provisa.google_workspace.directory import DelegationRefused, DirectoryRefused, NotAUser
from provisa.google_workspace.loader import listed_mailboxes, organisation_account

router = APIRouter(prefix="/admin/google-workspace", tags=["admin", "sources"])


class MailboxesBody(BaseModel):
    #: The source's choice, as its mapping states it: one of everyone, group, list.
    mailboxes: dict[str, Any]


def _admin_db() -> Any:
    from provisa.api.app import state

    assert state.admin_db is not None
    return state.admin_db


@router.post("/mailboxes/check")
async def check_mailboxes(request: Request, body: MailboxesBody) -> dict:
    """How many mailboxes the choice names in the organisation's directory now."""
    require_capability_request(request, "source_registration")
    from provisa.core.request_context import require_current_org
    from provisa.core.secrets_store import bound_to_request_org

    try:
        chosen = gws.parse(
            {"resources": [gws.MAIL], "mail_content": gws.MAIL_FULL, "mailboxes": body.mailboxes}
        ).mailboxes
    except gws.InvalidGoogleWorkspaceSource as invalid:
        raise ApiError(
            400, "google_workspace.mailboxes_invalid", str(invalid), None, error=str(invalid)
        ) from None
    try:
        # The key is the organisation's: its vault is bound for this request.
        async with bound_to_request_org():
            account, admin = await organisation_account(_admin_db(), require_current_org())
        found = await listed_mailboxes(account, admin, chosen)
    except MailPlatformRefused as refused:
        raise ApiError(refused.status, refused.code, str(refused), None, **refused.params) from None
    except DelegationRefused as refused:
        # Google does not say which scope is missing; the one this listing asked for is.
        raise ApiError(
            400,
            "google_workspace.scope_not_delegated",
            str(refused),
            None,
            scopes=", ".join(refused.scopes),
            reason=refused.reason,
        ) from None
    except NotAUser as refused:
        raise ApiError(
            400,
            "google_workspace.admin_not_a_user",
            str(refused),
            None,
            address=refused.address,
            reason=refused.reason,
        ) from None
    except DirectoryRefused as refused:
        raise ApiError(
            400,
            "google_workspace.directory_refused",
            str(refused),
            None,
            status=refused.status,
            reason=refused.reason,
        ) from None
    except ApiCallError as refused:
        # The service account's key, or Google's refusal of it for another reason.
        raise ApiError(
            400, "google_workspace.credential_refused", str(refused), None, reason=str(refused)
        ) from None
    return {"count": len(found)}
