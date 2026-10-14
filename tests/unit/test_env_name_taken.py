# Copyright (c) 2026 Kenneth Stott
# Canary: 9c4a2e17-6b83-4f05-a1d9-3e7b5c0f8d62
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An environment name the organization already has is refused as taken, not as an invalid name
(REQ-1488): the API answers 409 environments.name_taken, and only the first environment is
stored."""

# Requirements: REQ-1488

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from provisa.core import schema_admin
from provisa.core.database import Database, create_engine_from_url
from provisa.core.env_classes import INHERIT, REFUSED
from provisa.core.env_store import reserve_env
from provisa.core.environments import EnvironmentNameError, EnvironmentNameTaken
from provisa.core.schema_admin import environments

pytestmark = pytest.mark.asyncio


async def test_a_second_environment_by_one_name_is_refused_as_taken():
    db = Database(create_engine_from_url("sqlite+pysqlite:///:memory:"), name="env-taken")
    with db.engine.begin() as conn:
        schema_admin.metadata.create_all(conn)
    state = SimpleNamespace()
    choices = {"parent": "prod", "data_mode": INHERIT, "mutation_handling": REFUSED}
    await reserve_env(state, db, "acme", "staging", **choices)
    with pytest.raises(EnvironmentNameTaken, match="already has an environment 'staging'") as err:
        await reserve_env(state, db, "acme", "staging", **choices)
    assert isinstance(err.value, EnvironmentNameError)  # still a name the org cannot create
    async with db.acquire() as conn:
        held = (
            await conn.execute_core(
                select(func.count())
                .select_from(environments)
                .where(environments.c.name == "staging")
            )
        ).scalar_one()
    assert held == 1
