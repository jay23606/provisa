# Copyright (c) 2026 Kenneth Stott
# Canary: 20667f3c-7d46-446c-9a72-d68b9a8d0c5b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Which process serves a sandbox org (REQ-2006).

A demo sandbox is an org of its own, on an in-process DuckDB engine pinned to a file in the org's
folder (REQ-1992). Exactly one process may ever open that file, and every request for the sandbox
must reach that process: a DuckDB file is locked by the process that opens it, and the deployment's
API runs several uvicorn workers that share one listening socket, so the kernel, not Provisa, picks
which worker answers. The sandboxes therefore have a tier of their own: one single-worker process
(``PROVISA_SANDBOX_TIER=true``), reached through the UI server by the org's host (ui_server.py).

The tier is named by the org id. A sandbox's id begins ``sbx`` and a demo's template org's begins
``sbxtpl``; an ordinary org may not take either prefix (orgs_router._validate_new_org_id). Each
process builds runtimes for its own tier's orgs only (app._build_org_runtime), so a request that
reaches the other tier is refused by name rather than opening the file a second time.
"""

# Requirements: REQ-2006, REQ-1992, REQ-1309

from __future__ import annotations

import os
import secrets

from provisa.api.errors import ApiError

#: Every org of the sandbox tier: the sandboxes and the demos' template orgs.
SANDBOX_PREFIX = "sbx"
#: A demo's template org: ``sbxtpl<demo>``. A sandbox's id is hex after ``sbx``, so the two never
#: meet (``t`` is not a hex digit).
TEMPLATE_PREFIX = "sbxtpl"
_SANDBOX_ID_HEX = 12


def is_sandbox_tier_org(org_id: str) -> bool:
    """Whether ``org_id`` is served by the sandbox tier: a sandbox or a demo's template org."""
    return org_id.startswith(SANDBOX_PREFIX)


def is_template_org(org_id: str) -> bool:
    return org_id.startswith(TEMPLATE_PREFIX)


def template_org_id(demo: str) -> str:
    """The template org of the named demo ``demo`` (demo/named/<demo>/)."""
    return f"{TEMPLATE_PREFIX}{demo}"


def new_sandbox_org_id() -> str:
    """A fresh sandbox org id: ``sbx`` and 12 random hex digits."""
    return f"{SANDBOX_PREFIX}{secrets.token_hex(_SANDBOX_ID_HEX // 2)}"


def serves_sandboxes() -> bool:
    """Whether this process is the sandbox tier. Set by the deployment (docker-compose.app.yml's
    provisa-sandbox service), never per request."""
    value = os.environ.get("PROVISA_SANDBOX_TIER", "false")
    if value not in ("true", "false"):
        raise ValueError(f"PROVISA_SANDBOX_TIER must be true or false, got {value!r}")
    return value == "true"


def require_this_tier(org_id: str) -> None:
    """Refuse to serve ``org_id`` here when it belongs to the other tier.

    421 Misdirected Request: the request was well formed and the org exists, but this process does
    not serve it -- a sandbox opened here would be its DuckDB file opened by a second process."""
    sandbox = is_sandbox_tier_org(org_id)
    if sandbox == serves_sandboxes():
        return
    raise ApiError(
        421,
        "sandbox.wrong_tier",
        (
            f"Org {org_id!r} is a demo sandbox, served by the sandbox tier only"
            if sandbox
            else f"Org {org_id!r} is not a demo sandbox; this process serves demo sandboxes only"
        ),
        org=org_id,
    )
