# Copyright (c) 2026 Kenneth Stott
# Canary: c1851c52-ec37-4cb0-9196-93f05bf0f241
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A probing table's replica is rebuilt when its probe says the source changed, not when its
TTL passes (REQ-855: "probe -- re-probe the upstream ... and rebuild only on change, ignoring
TTL"; "Unchanged token -> keep the materialized rows, skip the re-pull/rebuild")."""

# Requirements: REQ-855, REQ-982, REQ-1907
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from provisa.core.models import SourceType
from provisa.federation import replica_builds

pytestmark = pytest.mark.asyncio

KEY = ("pg", "public", "orders")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _column(name: str, data_type: str = "bigint", pk: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, data_type=data_type, is_primary_key=pk, native_filter_type=None, embedding=False
    )


def _wired(monkeypatch, *, signal, watermark=None, source_type="postgresql", sentinel=None):
    source = SimpleNamespace(
        id="pg",
        type=SourceType(source_type),  # as a registered source carries it
        change_signal=signal,
        cache_ttl=300,
        sentinel_path=sentinel,
        path=None,
    )
    table = SimpleNamespace(
        source_id="pg",
        schema_name="public",
        table_name="orders",
        change_signal=None,
        watermark_column=watermark,
        probe_type=None,
        live=None,
        cache_ttl=None,
        file_glob=None,
        columns=[_column("id", pk=True), _column("updated_at", "timestamp")],
    )

    async def model_row(_state, _key):
        return source, table, [source]

    monkeypatch.setattr(replica_builds, "_model_row", model_row)
    engine = SimpleNamespace(engine=SimpleNamespace(backend=SimpleNamespace(dialect="duckdb")))
    return SimpleNamespace(federation_engine=engine, replica_nodes={KEY: "pg/public.orders"})


async def _due(state):
    return await replica_builds._next_refresh_at(state)(KEY, NOW)


async def test_a_ttl_tables_replica_is_due_when_its_ttl_passes(monkeypatch):
    assert await _due(_wired(monkeypatch, signal="ttl")) == NOW + timedelta(seconds=300)


@pytest.mark.parametrize("signal", ["probe", "ttl_probe"])
async def test_a_probing_tables_replica_has_no_clock_of_its_own(monkeypatch, signal):
    """Its node's probe, on the table's TTL, is what asks for a build."""
    assert await _due(_wired(monkeypatch, signal=signal, watermark="updated_at")) is None
    assert await _due(_wired(monkeypatch, signal=signal)) is None  # count probe


async def test_a_probing_table_whose_probe_cannot_answer_keeps_the_ttl_clock(monkeypatch):
    """An API source's hash probe with no sentinel has no token to give (REQ-982: it degrades
    to the TTL cadence)."""
    state = _wired(monkeypatch, signal="probe", source_type="openapi")
    assert await _due(state) == NOW + timedelta(seconds=300)
    with_sentinel = _wired(
        monkeypatch, signal="probe", source_type="openapi", sentinel="/data/_SUCCESS"
    )
    assert await _due(with_sentinel) is None


async def test_a_replica_no_node_probes_keeps_the_ttl_clock(monkeypatch):
    state = _wired(monkeypatch, signal="probe", watermark="updated_at")
    state.replica_nodes = {}
    assert await _due(state) == NOW + timedelta(seconds=300)


async def test_a_mail_tables_replica_follows_its_mailbox_probe(monkeypatch):
    """A source whose adapter asks its provider (Gmail's history id) has a probe that answers,
    so its replica is not re-read every TTL; a table the adapter has no probe for is."""
    from provisa.events import app_wiring

    async def token() -> str:
        return "t"

    def loader(*_a):
        return []

    loader.freshness_probe = lambda source, table: token if table.table_name == "orders" else None
    monkeypatch.setattr(
        app_wiring, "build_adapter_loaders", lambda *_a: {"google_workspace": loader}
    )
    state = _wired(monkeypatch, signal="probe", source_type="google_workspace")
    assert await _due(state) is None

    loader.freshness_probe = lambda source, table: None
    assert await _due(state) == NOW + timedelta(seconds=300)
