# Copyright (c) 2026 Kenneth Stott
# Canary: 8d3b6f20-1e4c-4a97-a5d1-63c9e2f7b048
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Saving a metric is an act in every domain its expression reads (REQ-1531).

A metric has no domain of its own: it is an object of every domain its expression reads, so saving
one needs each of them -- the domains the NEW expression reads, and the domains of the definition
it replaces.
"""

# Requirements: REQ-1531

from __future__ import annotations

import pytest
from sqlalchemy import select

from provisa.api.admin import schema_mutation
from provisa.api.admin.types import MetricInput
from provisa.core.schema_org import metrics
from tests.unit.test_admin_deletes_need_the_domain import _info, _names, plane  # noqa: F401


# --- metric: the domains its expression reads ----------------------------------------------------


async def test_a_metric_over_the_callers_domain_is_saved(plane):  # noqa: F811
    result = await schema_mutation.Mutation().upsert_metric(
        _info("sales_steward"), MetricInput(name="orders_total", expression="SUM(orders.amount)")
    )
    assert result.success is True
    assert "orders_total" in await _names(plane, metrics)


async def test_a_metric_reading_another_domain_is_refused(plane):  # noqa: F811
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await schema_mutation.Mutation().upsert_metric(
            _info("sales_steward"), MetricInput(name="owed", expression="SUM(invoices.amount)")
        )
    assert "owed" not in await _names(plane, metrics)


async def test_replacing_another_domains_metric_is_refused(plane):  # noqa: F811
    """The new expression reads only sales; the definition it replaces is finance's."""
    with pytest.raises(PermissionError, match="No access to domain 'finance'"):
        await schema_mutation.Mutation().upsert_metric(
            _info("sales_steward"), MetricInput(name="billed", expression="SUM(orders.amount)")
        )
    async with plane.acquire() as conn:
        stored = (
            await conn.execute_core(select(metrics.c.expression).where(metrics.c.name == "billed"))
        ).scalar_one()
    assert stored == "SUM(invoices.amount)"


async def test_a_caller_reaching_every_domain_saves_a_metric_across_two(plane):  # noqa: F811
    result = await schema_mutation.Mutation().upsert_metric(
        _info("everywhere"),
        MetricInput(name="net", expression="SUM(orders.amount) - SUM(invoices.amount)"),
    )
    assert result.success is True
