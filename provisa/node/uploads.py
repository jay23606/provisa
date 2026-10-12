# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Archives uploaded to Provisa as Node sources' code (REQ-1984), kept in the platform plane per
organisation by the content hash of the bundle they unpack to -- the hash a source records."""

# Requirements: REQ-1984
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from provisa.core.schema_admin import org_node_bundles as _t
from provisa.node.bundle import BundleRefused, content_hash, unpack
from provisa.node.install import UploadCode

if TYPE_CHECKING:
    from provisa.core.database import Database


async def put(
    admin_db: "Database", org_id: str, filename: str, data: bytes, *, actor: str | None
) -> str:
    """Keep the archive for ``org_id`` and return its bundle's content hash. The archive is
    unpacked first, with every guard an install applies, so one that cannot be used is refused
    here by name and nothing is kept. The same bundle uploaded again is kept once."""
    with tempfile.TemporaryDirectory(prefix="provisa-node-upload-") as scratch:
        found = content_hash(unpack(filename, data, Path(scratch)))
    async with admin_db.acquire() as conn:
        await conn.upsert(
            _t,
            {
                "org_id": org_id,
                "content_hash": found,
                "filename": filename,
                "archive": data,
                "uploaded_by": actor,
            },
            index_elements=["org_id", "content_hash"],
            update_columns=[],
        )
    return found


async def read(admin_db: "Database", org_id: str, content_hash_: str) -> UploadCode:
    """The archive ``org_id`` uploaded with that content hash, refused by name when there is none."""
    async with admin_db.acquire() as conn:
        row = (
            await conn.execute_core(
                select(_t.c.filename, _t.c.archive).where(
                    _t.c.org_id == org_id, _t.c.content_hash == content_hash_
                )
            )
        ).fetchone()
    if row is None:
        raise BundleRefused(
            "upload_not_found",
            f"there is no uploaded archive with content hash {content_hash_}",
            content_hash=content_hash_,
        )
    return UploadCode(row[0], bytes(row[1]))
