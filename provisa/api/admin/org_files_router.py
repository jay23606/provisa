# Copyright (c) 2026 Kenneth Stott
# Canary: 7b3e9c42-1d5a-4f86-8e0b-2a6c4d9f1e73
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1992: whether the org's file folder is encrypted, and the reference to its key.

- ``GET  /admin/org-files``: the setting, and the reference as stored (never a key).
- ``PUT  /admin/org-files``: set it. Applied on each node when the org's runtime is next built
  there; this node's runtime is rebuilt at once.
- ``POST /admin/org-files/generate-key``: a new 256-bit random key, answered once. Nothing keeps
  it: no log line, no store, no audit row holds the value. The admin puts it in the org's vault
  and sets the reference.

Gated on ``org_settings``: the folder and its key are the org's, and a platform_admin holds no data
capability anywhere (REQ-1337) -- it can neither read nor change them.
"""

# Requirements: REQ-1992
from __future__ import annotations

import base64
import secrets

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from provisa.api.admin._guards import require_active_org_id
from provisa.api.admin._platform_guard import require_org_settings
from provisa.api.errors import ApiError

router = APIRouter(tags=["admin"])


class OrgFilesBody(BaseModel):
    encrypted: bool
    key_reference: str | None = None


def _admin_db():
    from provisa.api.app import state

    assert state.admin_db is not None
    return state.admin_db


@router.get("/admin/org-files")
async def get_org_files(request: Request) -> dict:
    require_org_settings(request)
    from provisa.core.org_folder_crypt import read_settings

    org_id = require_active_org_id(request)
    settings = await read_settings(_admin_db(), org_id)
    return {
        "org_id": org_id,
        "encrypted": settings.encrypted,
        "key_reference": settings.key_reference,
    }


@router.put("/admin/org-files")
async def put_org_files(body: OrgFilesBody, request: Request) -> dict:
    require_org_settings(request)
    from provisa.core.org_folder_crypt import (
        FolderSettings,
        InvalidKeyReference,
        write_settings,
    )

    org_id = require_active_org_id(request)
    reference = (body.key_reference or "").strip() or None
    settings = FolderSettings(body.encrypted, reference)
    try:
        await write_settings(_admin_db(), org_id, settings)
    except InvalidKeyReference as invalid:
        raise ApiError(400, "org_files.invalid_reference", str(invalid), org=org_id) from None
    from provisa.api.app import state

    if org_id != state.org_id:
        # The org's runtime is built again at its next request, and its folder with it: its files
        # encrypted or decrypted under the setting just made. The deployment's own org applies it
        # when its process next starts.
        state.org_registry.invalidate_org(org_id)
    return {"org_id": org_id, "encrypted": settings.encrypted, "key_reference": reference}


@router.post("/admin/org-files/generate-key")
async def generate_key(request: Request, response: Response) -> dict:
    """A new random key, for the admin to put in the org's vault. Answered once, kept nowhere,
    and never cached on its way."""
    require_org_settings(request)
    require_active_org_id(request)
    response.headers["Cache-Control"] = "no-store"
    return {"key": base64.b64encode(secrets.token_bytes(32)).decode()}
