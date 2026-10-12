# Copyright (c) 2026 Kenneth Stott
# Canary: 28713e38-6f13-4882-8a84-bdc5367ef72e
#
# This source code is licensed under the Business Source License 1.1
"""The data-quality checkers of a table (REQ-1443): every checker table whose contract scans it,
found by the dataset its contract names (the checker's own parser), each with its last scan's
outcome -- a scan's worst check's -- or none before its first scan."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from provisa.core.database import Database, create_engine_from_url
from provisa.core.schema_org import registered_tables, sources
from provisa.dq.related import checkers_of, scan_outcome
from provisa.dq.results import RESULT_FIELDS, results_sa_table
from provisa.dq.scan import ensure_relation

ORDERS = "provisa/sales/orders"
SODA = f"dataset: {ORDERS}\nchecks:\n  - row_count:\n      must_be_greater_than: 0\n"
GX = json.dumps(
    {
        "meta": {"dataset": ORDERS},
        "expectations": [
            {"type": "expect_column_values_to_not_be_null", "kwargs": {"column": "customer"}}
        ],
    }
)
CUSTOMERS = (
    "dataset: provisa/sales/customers\nchecks:\n  - row_count:\n      must_be_greater_than: 0\n"
)


@pytest.fixture
def db(tmp_path):
    """A control plane with a Soda and a Great Expectations checker of orders, and a Soda checker
    of customers."""
    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'cp.db'}")
    with engine.begin() as c:
        registered_tables.metadata.create_all(c, tables=[sources, registered_tables])
        c.execute(insert(sources).values(id="soda-dq", type="soda"))
        c.execute(insert(sources).values(id="gx-dq", type="great_expectations"))
        c.execute(insert(sources).values(id="warehouse", type="postgresql"))
        for table_id, source, relation, alias, contract in (
            (7, "soda-dq", "orders_rows_soda_dq_dq", "orders_rows", SODA),
            (8, "gx-dq", "orders_nulls_gx_dq_dq", "orders_nulls", GX),
            (9, "soda-dq", "customers_rows_soda_dq_dq", "customers_rows", CUSTOMERS),
        ):
            c.execute(
                insert(registered_tables).values(
                    id=table_id,
                    source_id=source,
                    domain_id="sales",
                    schema_name="main",
                    table_name=relation,
                    alias=alias,
                    dq_contract=contract,
                    cache_ttl=600,
                )
            )
        c.execute(
            insert(registered_tables).values(
                id=1,
                source_id="warehouse",
                domain_id="sales",
                schema_name="sales",
                table_name="items",
            )
        )
    database = Database(engine, name="cp")
    yield database
    engine.dispose()


def _row(scan_time: datetime, check: str, outcome: str) -> dict:
    row: dict[str, object] = {field: None for field in RESULT_FIELDS}
    row.update(
        scan_id=scan_time.isoformat(), scan_time=scan_time, check_name=check, outcome=outcome
    )
    return row


@pytest.mark.asyncio
async def test_a_table_lists_every_checker_whose_contract_scans_it(db):
    earlier = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
    later = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    async with db.acquire() as conn:
        for relation in ("orders_rows_soda_dq_dq", "orders_nulls_gx_dq_dq"):
            await ensure_relation(conn, relation)
        await conn.execute_core_many(
            results_sa_table("orders_rows_soda_dq_dq").insert(),
            [
                _row(earlier, "row_count", "fail"),
                _row(later, "row_count", "pass"),
                _row(later, "freshness", "warn"),
            ],
        )
        found = await checkers_of(conn, ORDERS)

    assert [(c["table_id"], c["table_name"], c["source_id"]) for c in found] == [
        (7, "orders_rows", "soda-dq"),
        (8, "orders_nulls", "gx-dq"),
    ]
    # The last scan's worst check; the earlier scan's failure is history.
    assert (found[0]["outcome"], found[0]["scan_time"].replace(tzinfo=UTC)) == ("warn", later)
    # Not yet scanned: no outcome.
    assert (found[1]["outcome"], found[1]["scan_time"]) == (None, None)


@pytest.mark.asyncio
async def test_a_table_no_contract_scans_lists_none(db):
    async with db.acquire() as conn:
        assert await checkers_of(conn, "provisa/sales/items") == []


def test_a_scan_s_outcome_is_its_worst_check_s():
    assert scan_outcome(["pass", "skipped"]) == "pass"
    assert scan_outcome(["pass", "warn", "fail"]) == "fail"
    assert scan_outcome(["fail", "error"]) == "error"
    with pytest.raises(ValueError, match="maybe"):
        scan_outcome(["pass", "maybe"])
