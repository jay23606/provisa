# Copyright (c) 2026 Kenneth Stott
# Canary: 4ffe4300-acfe-4735-a61e-a53755dd9fed
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A large result kept in the org's folder, served to the user who asked for it (REQ-1191,
REQ-1192). The result and its owner are written by the local result sink
(``provisa.executor.local_results``); who is asking is this request's own identity."""

# Requirements: REQ-1191, REQ-1192

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/redirect-file/{name}")
async def redirect_file(name: str, request: Request) -> FileResponse:  # REQ-1191, REQ-1192
    """The result ``name``, for the user who asked for it: 404 when the org holds no such result
    or it is past ``redirect.ttl``, 403 when another user asked for it."""
    from provisa.executor import local_results
    from provisa.executor.redirect import RedirectConfig

    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="sign in to fetch a result")
    try:
        path, content_type = local_results.open_for(
            name, identity.user_id, RedirectConfig.from_env().ttl
        )
    except local_results.ResultFileNotFound:
        raise HTTPException(status_code=404, detail=f"no result {name!r}, or it has expired")
    except local_results.NotResultOwner:
        raise HTTPException(status_code=403, detail="the result belongs to another user")
    return FileResponse(path, media_type=content_type, filename=name)
