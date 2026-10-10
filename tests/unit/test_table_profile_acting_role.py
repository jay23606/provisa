# Copyright (c) 2026 Kenneth Stott
# Canary: 7c4b9e02-5d16-4a83-b3f7-1e9a6d0c2f58
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Profiling a view samples it as the role the request runs as (REQ-273, REQ-452).

The auth layer resolves ``X-Provisa-Role`` before the handler runs: a comma-separated set of held
roles becomes their meta-role, and a control-plane role resolves to the caller's data-plane role.
The sample is governed as THAT role. Read from the raw header instead, a set reached the pipeline
as one unknown role named ``a,b`` and a remapped role as the one the auth layer had replaced.
"""

# Requirements: REQ-273, REQ-452

from __future__ import annotations

import types

import pytest

from provisa.api.admin import table_profile_router as router_mod
from provisa.api.errors import ApiError


@pytest.fixture
def governed(monkeypatch) -> list[str]:
    """The roles the table's sample was read as."""
    seen: list[str] = []

    async def _read(_state, table_id, role_id, limit):
        seen.append(role_id)
        return types.SimpleNamespace(column_names=["id"], rows=[(1,)])

    monkeypatch.setattr(router_mod, "read_as_caller", _read)
    monkeypatch.setattr(
        router_mod, "table_for_steward", lambda request, state, table_id: {"draft": False}
    )
    state = types.SimpleNamespace(model_db=object(), federation_engine=object())
    monkeypatch.setattr(router_mod, "state", state)
    return seen


def _request(role: str | None):
    state = types.SimpleNamespace()
    if role is not None:
        state.role = role
    return types.SimpleNamespace(state=state)


@pytest.mark.parametrize(
    "header, established",
    [
        ("analyst,org_admin", "meta:analyst+org_admin"),  # a set acts as its meta-role
        ("platform_admin", "org_admin"),  # a control-plane role resolved to the data-plane one
        ("analyst", "analyst"),
    ],
)
async def test_the_sample_is_governed_as_the_established_role(governed, header, established):
    out = await router_mod.profile_table(_request(established), 7, x_provisa_role=header)
    assert governed == [established]
    assert out == {"columns": ["id"], "rows": [{"id": 1}], "rowCount": 1, "draft": False}


async def test_with_no_auth_layer_the_header_names_the_role(governed):
    await router_mod.profile_table(_request(None), 7, x_provisa_role="analyst")
    assert governed == ["analyst"]


async def test_no_role_at_all_is_refused(governed):
    with pytest.raises(ApiError) as err:
        await router_mod.profile_table(_request(None), 7, x_provisa_role=None)
    assert (err.value.status_code, err.value.code) == (400, "profile.role_header_required")
    assert governed == []
