# Copyright (c) 2026 Kenneth Stott
# Canary: 9a7bc542-456d-467b-977f-451986f449a0
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1868: PgDuckdbMotherDuckConnector — live ATTACH_RW into a MotherDuck-hosted
DuckDB database via pg_duckdb's own FOREIGN DATA WRAPPER (TYPE 'motherduck').

Pure logic — the async ``probe(fetch)`` is driven by a fake fetch callable; no
live Postgres. The gate specific to MotherDuck is the FDW registration check
(pg_foreign_data_wrapper), distinct from the scan-connector probes that check
for a scanner function.
"""

from __future__ import annotations

import pytest

from tests.helpers import attaching
from provisa.core.models import Source, SourceType
from provisa.federation.connector import Mechanism
from provisa.federation.connector_duckdb import PgDuckdbMotherDuckConnector


def _src(sid: str, **kw):
    fields = {"password": "md_token_abc", **kw}
    return attaching(Source(id=sid, type=SourceType.motherduck, **fields), sid)


class _FakeFetch:
    """Async fetch keyed on distinctive substrings of the probe SQL."""

    def __init__(self, *, preloaded: bool, fdw_registered: bool):
        self._preloaded = preloaded
        self._fdw_registered = fdw_registered

    async def __call__(self, sql: str):
        if "shared_preload_libraries" in sql:
            return [{"v": "pg_duckdb" if self._preloaded else ""}]
        if "pg_foreign_data_wrapper" in sql:
            return [{"one": 1}] if self._fdw_registered else []
        return []


# ---- connector identity / mechanism (REQ-1868) ------------------------------


def test_motherduck_connector_identity():
    c = PgDuckdbMotherDuckConnector()
    assert c.engine == "postgres"
    assert c.source_type == "motherduck"
    assert c.key == "pg_duckdb_motherduck"
    assert c.mechanism is Mechanism.ATTACH_RW  # live in place, read + write
    assert c.reads_in_place is True


def test_motherduck_capability_full_pushdown_and_writable():
    cap = PgDuckdbMotherDuckConnector().capability()
    assert cap.predicate_pushdown is True
    assert cap.join_pushdown is True
    assert cap.aggregate_pushdown is True
    assert cap.write is True


# ---- attach DDL: CREATE SERVER + USER MAPPING (REQ-1868) --------------------


def test_details_name_the_database_token_and_the_servers_options():
    details = PgDuckdbMotherDuckConnector().details(
        _src("mdsrc", password="secrettoken", database="sample_data")
    )
    # pg_duckdb's sync creates the tables: nothing is imported, so no foreign-schema DDL
    assert details == {
        "motherduck": {"database": "sample_data", "token": "secrettoken", "server_options": {}}
    }


def test_server_options_come_from_federation_hints_when_set():
    details = PgDuckdbMotherDuckConnector().details(
        _src(
            "mdsrc2",
            database="analytics",
            federation_hints={
                "default_database": "analytics",
                "tables_owner_role": "app_role",
                "background_catalog_refresh_inactivity_timeout": "10m",
            },
        )
    )
    assert details["motherduck"]["server_options"] == {
        "default_database": "analytics",
        "tables_owner_role": "app_role",
        "background_catalog_refresh_inactivity_timeout": "10m",
    }


def test_details_raise_when_the_database_is_not_named():
    with pytest.raises(ValueError, match="name the MotherDuck database"):
        PgDuckdbMotherDuckConnector().details(_src("mdsrc5"))


def test_details_raises_when_token_missing():
    with pytest.raises(ValueError, match="password.*MotherDuck token"):
        PgDuckdbMotherDuckConnector().details(_src("mdsrc4", password="", database="d"))


# ---- functional-truth probe (REQ-904/1868) ----------------------------------


@pytest.mark.asyncio
async def test_probe_available_when_preloaded_and_fdw_registered():
    r = await PgDuckdbMotherDuckConnector().probe(_FakeFetch(preloaded=True, fdw_registered=True))
    assert r.available is True


@pytest.mark.asyncio
async def test_probe_unavailable_when_not_preloaded():
    r = await PgDuckdbMotherDuckConnector().probe(_FakeFetch(preloaded=False, fdw_registered=True))
    assert r.available is False
    assert "shared_preload_libraries" in r.reason


@pytest.mark.asyncio
async def test_probe_unavailable_when_fdw_not_registered():
    r = await PgDuckdbMotherDuckConnector().probe(_FakeFetch(preloaded=True, fdw_registered=False))
    assert r.available is False
    assert "foreign data wrapper" in r.reason
    assert r.remediation and "CREATE EXTENSION" in r.remediation


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
