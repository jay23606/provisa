# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A code source's uploads, as the source form sends them (REQ-1984, REQ-1993).

``POST /admin/orgs/{org_id}/code-uploads/archive?filename=...`` keeps an archive of code (``.zip``,
``.tgz``, ``.tar.gz``) and answers the content hash of the code it unpacks to, which the source
records; an archive that cannot be used is refused by name and nothing is kept.
``POST .../lockfile?filename=...`` keeps a lockfile given beside a package reference and answers
the SHA-256 of its bytes. The body is the file's bytes. Each is kept in the organisation's store by
its hash (provisa/codesource/uploads.py), and opened by ``source_registration`` held in THAT
organisation: uploading code is part of registering a source.
"""

# Requirements: REQ-1984, REQ-1993
from __future__ import annotations

from fastapi import APIRouter, Request

from provisa.api.admin.environments_router import _caller_user_id
from provisa.api.admin.secrets_router import _admin_pool
from provisa.api.errors import ApiError
from provisa.codesource import uploads
from provisa.codesource.bundle import BundleRefused

router = APIRouter(prefix="/admin/orgs/{org_id}/code-uploads", tags=["admin"])

#: The largest upload kept: an archive is bounded again by what it expands to (bundle.py).
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


async def _guard(request: Request, org_id: str) -> str | None:
    from provisa.api.admin.capabilities import _resolved_capabilities
    from provisa.api.app import state
    from provisa.security.rights import Capability

    user_id = _caller_user_id(request)
    if user_id is None:
        return None  # dev mode -- no auth configured, matching every other admin guard
    caps = _resolved_capabilities(request.state.identity, state)
    if (
        Capability.SOURCE_REGISTRATION.value not in caps
        or getattr(request.state, "active_org_id", None) != org_id
    ):
        raise ApiError(
            403,
            "codesource.source_registration_required",
            "Uploading a code source's code needs source registration in this organisation",
            None,
        )
    return user_id


async def _body(request: Request) -> bytes:
    data = await request.body()
    if not data:
        raise ApiError(400, "codesource.upload_empty", "The upload is empty", None)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(
            413,
            "codesource.upload_too_large",
            f"An upload is at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            None,
        )
    return data


def _refusal(refused: BundleRefused) -> ApiError:
    return ApiError(400, refused.code, str(refused), None, **refused.params)


@router.post("/archive")
async def upload_archive(request: Request, org_id: str, filename: str) -> dict:
    """Keep an archive of code; its code's content hash."""
    actor = await _guard(request, org_id)
    data = await _body(request)
    try:
        found = await uploads.put(_admin_pool(), org_id, filename, data, actor=actor)
    except BundleRefused as refused:
        raise _refusal(refused) from None
    return {"content_hash": found, "filename": filename}


@router.post("/lockfile")
async def upload_lockfile(request: Request, org_id: str, filename: str) -> dict:
    """Keep a lockfile given beside a package reference; the SHA-256 of its bytes."""
    actor = await _guard(request, org_id)
    data = await _body(request)
    found = await uploads.put_file(_admin_pool(), org_id, filename, data, actor=actor)
    return {"sha256": found, "filename": filename}
