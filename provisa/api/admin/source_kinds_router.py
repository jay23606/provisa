"""What the Sources form needs to know of a source kind before anything is saved.

One fact so far: whether a source of the kind must state its Cache TTL itself (REQ-1907). The
rule is the server's (``_landing_ttl.source_states_the_clock``); the form asks rather than keep
its own list of kinds.
"""

# Requirements: REQ-1907
from __future__ import annotations

from fastapi import APIRouter, Request

from provisa.api.admin._landing_ttl import source_states_the_clock
from provisa.api.admin.capabilities import require_capability_request

router = APIRouter(prefix="/admin/source-kinds", tags=["admin"])


@router.get("/{kind}")
async def source_kind(request: Request, kind: str) -> dict:
    require_capability_request(request, "source_registration")
    return {"cache_ttl_required": source_states_the_clock(kind)}
