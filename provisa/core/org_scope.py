# Copyright (c) 2026 Kenneth Stott
# Canary: 0b5d7e93-2c4a-4f61-8a3e-9d1c6f2b5e07
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The org a per-source thing belongs to (REQ-1992).

A source id is unique only within its org (each org's sources are in its own schema), so
anything kept for a source on this node -- its connector server, its files -- is kept under the
org as well as the source. The org is the one bound to the work at hand; work with no org bound
is refused by name (``require_current_org``).
"""

# Requirements: REQ-1992
from __future__ import annotations

import re

_ORG_ID = re.compile(r"[A-Za-z0-9_]+")


def current_org_segment() -> str:
    """The bound org's id, as one path segment: refused unless it is one."""
    from provisa.core.request_context import require_current_org

    org_id = require_current_org()
    if not _ORG_ID.fullmatch(org_id):
        raise ValueError(f"org id {org_id!r} is not one path segment")
    return org_id


def source_key(source_id: str) -> tuple[str, str]:
    """What a source is known by on this node: its org and its id."""
    return current_org_segment(), source_id
