# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The claim types an org declares as pseudo-roles (REQ-2057).

Each declared type becomes a parent role, and each value a member's attributes give it a sub-role
``<type>__<value>``. The org's own list (org_settings ``claim_roles``) replaces the deployment
config's; none stored, the config's applies. Gated by ``user_management``, as roles are.
"""

# Requirements: REQ-2057

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from provisa.api.admin.capabilities import require_capability_request
from provisa.api.errors import ApiError
from provisa.security.rights import Capability

router = APIRouter(prefix="/admin/claim-roles", tags=["admin"])

ORG = "org"
DEPLOYMENT = "deployment"


class ClaimRolesBody(BaseModel):
    claim_types: list[str]


def _answer(state) -> dict:
    from provisa.auth.pseudo_roles import declared_claim_roles

    return {
        "claim_types": declared_claim_roles(state),
        "source": ORG if "claim_roles" in state.settings_overrides else DEPLOYMENT,
    }


@router.get("")
async def get_claim_roles(request: Request) -> dict:
    """The declared claim types, and whether they are the org's own list or the deployment's."""
    require_capability_request(request, Capability.USER_MANAGEMENT.value)
    from provisa.api.app import state

    return _answer(state)


@router.put("")
async def put_claim_roles(body: ClaimRolesBody, request: Request) -> dict:
    """Declare the org's claim types, replacing the list it had."""
    require_capability_request(request, Capability.USER_MANAGEMENT.value)
    from provisa.api.app import state
    from provisa.auth.attributes import attribute_name_problem, normalize_name
    from provisa.core.org_settings import read_org_overrides, write_org_overrides

    types: list[str] = []
    for name in body.claim_types:
        problem = attribute_name_problem(name)
        if problem is not None:
            code, message = problem
            shown = normalize_name(name) if code == "name_reserved" else name
            raise ApiError(422, f"claim_roles.{code}", message, name=shown)
        normalized = normalize_name(name)
        if normalized not in types:
            types.append(normalized)
    model_db = state.model_db
    if model_db is None:
        raise ApiError(503, "claim_roles.database_not_connected", "Database not connected")
    identity = getattr(request.state, "identity", None)
    await write_org_overrides(
        model_db, {"claim_roles": types}, updated_by=getattr(identity, "user_id", "anonymous")
    )
    # A request's pseudo-roles are read off the bound runtime: refreshed here, as settings are.
    state.settings_overrides = await read_org_overrides(model_db)
    return _answer(state)
