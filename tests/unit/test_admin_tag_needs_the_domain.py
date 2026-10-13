# Copyright (c) 2026 Kenneth Stott
# Canary: 4c7d1e52-9d0a-4a38-b4f4-1d6a2c0e9b77
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Assigning or removing a tag is an act in its target's domain (REQ-1531).

A tag assignment's domain is its target's: the table's, the table a column sits in, the table a
relationship starts at, the domain a command sits in, the domains a source is open to. A target
that is not there is answered as not found.
"""

# Requirements: REQ-1531

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from provisa.api.admin import schema_mutation
from provisa.api.admin.types import TagAssignmentInput
from provisa.core.schema_org import registered_tables, sources, tag_assignments, tags
from tests.unit.test_admin_deletes_need_the_domain import _info, _names, plane  # noqa: F401


async def _table_id(db, name: str) -> int:
    async with db.acquire() as conn:
        return (
            await conn.execute_core(
                select(registered_tables.c.id).where(registered_tables.c.table_name == name)
            )
        ).scalar_one()


@pytest.fixture
async def tagged(plane, monkeypatch):  # noqa: F811
    """A user tag that applies to every kind of object, and a source open to finance alone."""

    async def _refresh() -> None:
        return None

    monkeypatch.setattr(schema_mutation, "_refresh_config_tags", _refresh)
    async with plane.acquire() as conn:
        await conn.execute_core(
            insert(tags).values(
                id="reviewed",
                applies_to=["source", "table", "column", "relationship", "command"],
            )
        )
        await conn.execute_core(
            insert(sources).values(id="ledger_db", type="postgresql", allowed_domains=["finance"])
        )
    return plane


# --- tag assignment: the target's domain ---------------------------------------------------------


def _on(kind: str, **target) -> TagAssignmentInput:
    return TagAssignmentInput(tag_id="reviewed", object_type=kind, **target)


async def _assigned(db) -> set[str]:
    return await _names(db, tag_assignments, "object_key")


async def test_a_tag_on_the_callers_own_table_is_assigned_and_removed(tagged):
    table_id = await _table_id(tagged, "orders")
    mutation = schema_mutation.Mutation()
    assert (
        await mutation.assign_tag(_info("sales_steward"), _on("table", table_id=table_id))
    ).success
    assert await _assigned(tagged) == {f"table:{table_id}"}
    assert (
        await mutation.unassign_tag(_info("sales_steward"), _on("table", table_id=table_id))
    ).success
    assert await _assigned(tagged) == set()


@pytest.mark.parametrize("kind", ["table", "column"])
async def test_a_tag_on_another_domains_table_or_column_is_refused(tagged, kind):
    target = {"table_id": await _table_id(tagged, "invoices")}
    if kind == "column":
        target["column_name"] = "amount"
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await schema_mutation.Mutation().assign_tag(_info("sales_steward"), _on(kind, **target))
    assert await _assigned(tagged) == set()


async def test_a_relationship_tag_needs_the_domain_the_edge_starts_in(tagged):
    mutation = schema_mutation.Mutation()
    # ``across`` starts at orders (sales): the edge hangs off its source table.
    assert (
        await mutation.assign_tag(
            _info("sales_steward"), _on("relationship", relationship_id="across")
        )
    ).success
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await mutation.assign_tag(
            _info("sales_steward"), _on("relationship", relationship_id="in_finance")
        )


async def test_a_command_tag_needs_the_domain_the_command_sits_in(tagged):
    mutation = schema_mutation.Mutation()
    assert (
        await mutation.assign_tag(_info("sales_steward"), _on("command", command_name="of_sales"))
    ).success
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await mutation.assign_tag(_info("sales_steward"), _on("command", command_name="of_finance"))


async def test_a_source_tag_needs_every_domain_the_source_is_open_to(tagged):
    mutation = schema_mutation.Mutation()
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await mutation.assign_tag(_info("sales_steward"), _on("source", source_id="ledger_db"))
    # ``pg`` names no domains, which opens it to all of them: reaching one is not reaching it.
    with pytest.raises(PermissionError):
        await mutation.assign_tag(_info("sales_steward"), _on("source", source_id="pg"))
    assert (await mutation.assign_tag(_info("everywhere"), _on("source", source_id="pg"))).success


async def test_removing_a_tag_from_another_domains_table_is_refused(tagged):
    table_id = await _table_id(tagged, "invoices")
    mutation = schema_mutation.Mutation()
    assert (await mutation.assign_tag(_info("everywhere"), _on("table", table_id=table_id))).success
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await mutation.unassign_tag(_info("sales_steward"), _on("table", table_id=table_id))
    assert await _assigned(tagged) == {f"table:{table_id}"}


async def test_a_tag_on_a_table_that_is_not_there_is_not_found(tagged):
    result = await schema_mutation.Mutation().assign_tag(
        _info("sales_steward"), _on("table", table_id=987654)
    )
    assert (result.success, result.code) == (False, "schema.tag_target_not_found")
