# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A demo sandbox's disk cap (REQ-2006): its whole folder -- its DuckDB store and its uploads --
may hold at most ``sandbox.disk_limit`` bytes. A write that would pass it is refused by name, before
it is made: an upload (core.source_uploads) and every write to the sandbox's store
(federation.materialize_broker). Any other org's folder is not measured."""

# Requirements: REQ-2006, REQ-1992

from __future__ import annotations

import os
from pathlib import Path

from provisa.core import org_files, settings_registry
from provisa.core.org_ids import is_demo_sandbox


class SandboxDiskFull(Exception):
    """A write would take a demo sandbox's folder past its disk cap."""

    code = "sandbox.disk_full"

    def __init__(self, org_id: str, used: int, adding: int, limit: int) -> None:
        super().__init__(
            f"This sandbox holds {used} bytes of its {limit}-byte limit; "
            f"{adding} more cannot be written"
            if adding
            else f"This sandbox has used its {limit}-byte limit"
        )
        self.params = {"org": org_id, "used": used, "adding": adding, "limit": limit}


def folder_bytes(org_id: str) -> int:
    """What ``org_id``'s folder holds on this node, in bytes."""
    total = 0
    for root, _dirs, files in os.walk(org_files.folder(org_id)):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except FileNotFoundError:  # removed while measured (a finished temporary file)
                continue
    return total


def require_room(org_id: str, adding: int = 0) -> None:
    """Refuse a write of ``adding`` bytes to ``org_id``'s folder when it is a demo sandbox's and
    the write would take it past ``sandbox.disk_limit``. A store write's size is not known before
    it is made, so it is refused once the folder is full (``adding`` 0)."""
    if not is_demo_sandbox(org_id):
        return
    limit = int(settings_registry.value("sandbox.disk_limit"))
    used = folder_bytes(org_id)
    if used + adding > limit or used >= limit:
        raise SandboxDiskFull(org_id, used, adding, limit)


def require_room_after(org_id: str, held: int, adding: int) -> None:
    """:func:`require_room` for a write in progress: ``held`` is what the folder held before it
    began, measured once, and ``adding`` what it has written so far."""
    if not is_demo_sandbox(org_id):
        return
    limit = int(settings_registry.value("sandbox.disk_limit"))
    if held + adding > limit:
        raise SandboxDiskFull(org_id, held, adding, limit)


def org_of_store(db_path: str) -> str | None:
    """The org whose folder holds the store file ``db_path``, or None for a file outside the
    orgs' folders."""
    try:
        relative = Path(db_path).resolve().relative_to(org_files.orgs_dir().resolve())
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None
