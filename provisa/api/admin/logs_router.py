# Copyright (c) 2026 Kenneth Stott
# Canary: f4573ebe-1215-4c67-bef5-a44bdbccae3e
#
# This source code is licensed under the Business Source License 1.1
"""What the Sources form asks about a Logs source (REQ-1996): the formats it may name, and what
its files hold before it is saved -- the files its glob matches, the columns its format gives,
the first rows. Refused by name where the files may not be read (``provisa.logs.roots``)."""

# Requirements: REQ-1996
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from provisa.api.admin.capabilities import require_capability_request
from provisa.api.errors import ApiError
from provisa.logparse import catalog
from provisa.logs import preview as logs_preview
from provisa.logs import settings as logs_settings
from provisa.logs.roots import LogPathRefused

router = APIRouter(prefix="/admin/logs", tags=["admin", "sources"])

#: How many rows a preview shows.
PREVIEW_ROWS = 20


class PreviewBody(BaseModel):
    #: The source's settings, as its mapping states them.
    mapping: dict[str, Any]


@router.get("/formats")
async def formats(request: Request) -> dict:
    require_capability_request(request, "source_registration")
    return {"formats": catalog()}


@router.post("/preview")
async def preview(request: Request, body: PreviewBody) -> dict:
    require_capability_request(request, "source_registration")
    try:
        settings = logs_settings.parse(body.mapping)
    except logs_settings.InvalidLogsSource as invalid:
        raise ApiError(400, "logs.invalid", str(invalid), None, error=str(invalid)) from None
    try:
        return await asyncio.to_thread(logs_preview.preview, settings, PREVIEW_ROWS)
    except LogPathRefused as refused:
        raise ApiError(403, "logs.path_refused", str(refused), None, reason=str(refused)) from None
