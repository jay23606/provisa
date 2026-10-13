# Copyright (c) 2026 Kenneth Stott
# Canary: 75aaf7b8-ebee-476f-8509-ec4a9af4a569
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A capped PostgreSQL source's DuckDB pool holds its share of the cap and waits (REQ-1909).

The postgres extension gives each attached database a pool of up to 18 connections that connects
past its limit ('force'), so a worker could hold far more connections to a source than its
max_live_concurrency allows: the live permits cap queries, not connections. A capped source's pool
holds ``max_live_concurrency // workers`` and waits for a free connection; a cap below the worker
count is refused by name, at save and at attach.
"""

# Requirements: REQ-1909

from __future__ import annotations

import pytest

from provisa.api.admin.schema_mutation import _validate_source_load_management
from provisa.api.admin.types import SourceInput
from provisa.core.models import Source, SourceType
from provisa.federation.connector_duckdb import (
    DuckDBPostgresConnector,
    PoolCapBelowWorkers,
    pg_pool_max_connections,
)


@pytest.fixture
def workers(monkeypatch):
    def _set(n: int) -> None:
        monkeypatch.setattr("provisa.core.boot_lock.expected_workers", lambda: n)

    return _set


def _pg(cap: int | None) -> Source:
    return Source(
        id="orders-pg",
        type=SourceType.postgresql,
        host="db",
        port=5432,
        database="orders",
        username="reader",
        max_live_concurrency=cap,
    )


def test_the_cap_is_divided_over_the_workers(workers):
    workers(4)
    assert pg_pool_max_connections("orders-pg", 8) == 2
    assert pg_pool_max_connections("orders-pg", 9) == 2  # never more than the cap in total


def test_an_uncapped_source_has_no_pool_size_of_its_own(workers):
    workers(4)
    assert pg_pool_max_connections("orders-pg", None) is None


def test_a_cap_below_the_worker_count_is_refused_by_name(workers):
    workers(4)
    with pytest.raises(
        PoolCapBelowWorkers, match=r"'orders-pg'.*max_live_concurrency 3.*4 workers"
    ):
        pg_pool_max_connections("orders-pg", 3)


def test_a_capped_source_is_attached_with_its_share_and_waits(workers):
    workers(2)
    details = DuckDBPostgresConnector().details(_pg(6))
    assert details["configure_pool"] == (
        "FROM postgres_configure_pool(catalog_name='_src_orders-pg', "
        "max_connections=3, acquire_mode='wait')"
    )


def test_an_uncapped_source_is_attached_as_the_extension_builds_it(workers):
    workers(2)
    assert "configure_pool" not in DuckDBPostgresConnector().details(_pg(None))


def test_the_attach_refuses_a_cap_below_the_worker_count(workers):
    workers(4)
    with pytest.raises(PoolCapBelowWorkers, match="'orders-pg'"):
        DuckDBPostgresConnector().details(_pg(2))


def test_the_runtime_configures_the_pool_right_after_the_attach(workers):
    from provisa.federation.duckdb_runtime import DuckDBFederationRuntime

    workers(2)
    executed: list[str] = []
    runtime = DuckDBFederationRuntime.__new__(DuckDBFederationRuntime)
    runtime._con = type("_Con", (), {"execute": lambda _self, sql: executed.append(sql)})()
    runtime._pg_ext_loaded = False
    runtime._raw_attached = set()
    runtime._raw_attach_ddl = {}
    source = _pg(4)
    runtime._attach_raw(source, DuckDBPostgresConnector().details(source))
    attach = next(i for i, sql in enumerate(executed) if sql.startswith("ATTACH "))
    assert executed[attach + 1 :] == [
        "FROM postgres_configure_pool(catalog_name='_src_orders-pg', "
        "max_connections=2, acquire_mode='wait')"
    ]


def test_an_environments_own_attach_has_its_own_pool_configured(workers):
    """REQ-1529, REQ-1909: a source an environment binds to another database is attached a second
    time under a catalog of its own; the pool configured is that catalog's, not the first one's."""
    from provisa.federation.duckdb_runtime import DuckDBFederationRuntime

    workers(2)
    executed: list[str] = []
    runtime = DuckDBFederationRuntime.__new__(DuckDBFederationRuntime)
    runtime._con = type("_Con", (), {"execute": lambda _self, sql: executed.append(sql)})()
    runtime._pg_ext_loaded = True
    runtime._raw_attached = set()
    runtime._raw_attach_ddl = {}
    runtime._catalog_of = lambda _source: "dev"  # type: ignore[method-assign]
    runtime._ext_loaded = set()
    runtime._engine = type("_Engine", (), {"connector_for": lambda _self, _t: object()})()
    source = _pg(4)
    runtime._attach_raw(source, DuckDBPostgresConnector().details(source))
    source.database = "orders_dev"
    alias = runtime._attach_raw(source, DuckDBPostgresConnector().details(source))
    assert alias == "_src_orders-pg__dev"
    assert executed[-1] == (
        "FROM postgres_configure_pool(catalog_name='_src_orders-pg__dev', "
        "max_connections=2, acquire_mode='wait')"
    )


def _input(cap: int | None) -> SourceInput:
    return SourceInput(id="orders-pg", type="postgresql", max_live_concurrency=cap)


def test_saving_a_cap_below_the_worker_count_is_refused_on_duckdb(workers, monkeypatch):
    workers(4)
    monkeypatch.setattr("provisa.api.admin.schema_mutation._engine_name", lambda: "duckdb")
    result = _validate_source_load_management(_input(3))
    assert result is not None and result.success is False
    assert result.code == "schema.max_live_concurrency_below_workers"
    assert "4 workers" in result.message


def test_saving_a_cap_the_workers_can_share_is_accepted(workers, monkeypatch):
    workers(4)
    monkeypatch.setattr("provisa.api.admin.schema_mutation._engine_name", lambda: "duckdb")
    assert _validate_source_load_management(_input(4)) is None


def test_another_engine_does_not_divide_the_cap(workers, monkeypatch):
    workers(4)
    monkeypatch.setattr("provisa.api.admin.schema_mutation._engine_name", lambda: "trino")
    assert _validate_source_load_management(_input(3)) is None
