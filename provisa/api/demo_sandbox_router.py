# Copyright (c) 2026 Kenneth Stott
# Canary: 1a152f45-62b2-46e6-95f9-740fca277227
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Opening a demo sandbox from the live demos page (REQ-2006).

``POST /public/demos/{name}`` needs no sign-in: it opens a visitor's sandbox of the published demo
``name`` and answers the sandbox's org and the visitor's token, which the page keeps and the
sandbox's own address is then used with. Served by the sandbox tier only (the UI server routes the
path there, ui_server.DEMO_OPEN_PREFIX); every other process refuses it by name."""

# Requirements: REQ-2006, REQ-1035

from __future__ import annotations

from fastapi import APIRouter

from provisa.api.errors import ApiError

router = APIRouter(prefix="/public/demos", tags=["demo sandboxes"])


@router.post("/{name}")
async def open_demo(name: str) -> dict:
    from provisa.api.demo_sandbox import VISITOR, open_sandbox
    from provisa.api.sandbox_tier import serves_sandboxes

    if not serves_sandboxes():
        raise ApiError(
            421,
            "sandbox.wrong_tier",
            "Demo sandboxes are opened by the sandbox tier only",
        )
    opened = await open_sandbox(name, kind=VISITOR)
    return {"org_id": opened.org_id, "demo": opened.demo, "token": opened.token}
