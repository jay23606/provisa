# Copyright (c) 2026 Kenneth Stott
# Canary: 883c0718-fafd-4982-946d-e713e8763837
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What the Sources form needs to know of a source kind before anything is saved.

Each fact is a rule the server owns; the form asks rather than keep its own list of kinds:

- ``cache_ttl_required``: a source of the kind must state its Cache TTL itself (REQ-1907,
  ``_landing_ttl.source_states_the_clock``);
- ``sentinel_path``: a source of the kind can have a sentinel marker (REQ-1148,
  ``events.sentinel_probe.applies_to``);
- ``tables_land``: every table of a source of the kind is served from a replica under the
  engine bound here, so a table registered under a ttl signal needs a Cache TTL, its own or
  its source's (REQ-1907, ``_landing_ttl.kind_lands``).
"""

# Requirements: REQ-1907, REQ-1148
from __future__ import annotations

from fastapi import APIRouter, Request

from provisa.api.admin._landing_ttl import kind_lands, source_states_the_clock
from provisa.api.admin.capabilities import require_capability_request
from provisa.events import sentinel_probe

router = APIRouter(prefix="/admin/source-kinds", tags=["admin"])


@router.get("/{kind}")
async def source_kind(request: Request, kind: str) -> dict:
    require_capability_request(request, "source_registration")
    return {
        "cache_ttl_required": source_states_the_clock(kind),
        "sentinel_path": sentinel_probe.applies_to(kind),
        "tables_land": kind_lands(kind),
    }
