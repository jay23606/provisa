# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An edited source's direct pool is opened with its connection extras (REQ-1731).

updateSource reopened the pool with host, port, database and credentials only, so an Exasol
source's certificate pin (federation_hints' tls_fingerprint) never reached the driver: it dialled
unpinned, the self-signed certificate was refused, and the Register form listed no schemas (the
swap lane's exasol case on main 15bd4bf1b)."""

# Requirements: REQ-1731

from __future__ import annotations

import contextlib
import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from provisa.api.admin.types import SourceInput
from tests.unit.test_landing_ttl_admin import _db, _mutation


class _Pools:
    def __init__(self) -> None:
        self.added: list[dict] = []

    async def remove(self, source_id: str) -> None:
        return None

    async def add(self, **kwargs) -> None:
        self.added.append(kwargs)


@pytest.mark.asyncio
async def test_an_edited_exasol_source_dials_with_its_certificate_pin(tmp_path):
    import provisa.api.app as app_mod

    pools = _Pools()

    @contextlib.asynccontextmanager
    async def _bound():
        yield

    async with _db(tmp_path, source_type="exasol", source_ttl=60) as db:
        m, p = _mutation(db)
        with (
            p,
            patch("provisa.api.admin.capabilities.require_capability", return_value=None),
            patch("provisa.core.secrets_store.bound_to_request_org", _bound),
            patch.object(type(app_mod.state), "source_pools", PropertyMock(return_value=pools)),
        ):
            result = await m.update_source(
                MagicMock(),
                SourceInput(
                    id="s",
                    type="exasol",
                    host="h",
                    port=8563,
                    database="PROVISA",
                    username="sys",
                    password="",
                    change_signal="ttl",
                    cache_ttl=60,
                    federation_hints_json=json.dumps({"tls_fingerprint": "ABC123"}),
                ),
            )
        assert result.success is True, result.message
        assert [a["extra"] for a in pools.added] == [{"tls_fingerprint": "ABC123"}]
