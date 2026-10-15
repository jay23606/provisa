# Copyright (c) 2026 Kenneth Stott
# Canary: 986a0f24-8f11-47cf-8d65-2adf375757b3
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Unit tests for SLA monitor and compliance reporter (REQ-074, REQ-506)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from provisa.audit.compliance_reporter import export_audit_log
from provisa.audit.sla_monitor import (
    AVAILABILITY,
    EVALUATE_MINUTES,
    LATENCY,
    SlaLimits,
    breached,
    check_sla_breach,
    get_sla_summary,
    record_evaluation,
    sla_limits,
)


# ---------------------------------------------------------------------------
# service level: limits, breaches and their record (REQ-506)
# ---------------------------------------------------------------------------

_LIMITS = SlaLimits(p99_limit_ms=5000, availability_min_pct=99.9)


def _summary(p99: float, availability: float, count: int = 10) -> dict:
    return {"count": count, "p99_ms": p99, "availability_pct": availability}


def test_check_sla_breach_p99_over_limit():
    assert check_sla_breach(_summary(5001.0, 100.0), _LIMITS) is True


def test_check_sla_breach_p99_at_limit_passes():
    assert check_sla_breach(_summary(5000.0, 100.0), _LIMITS) is False


def test_check_sla_breach_availability_below_threshold():
    assert check_sla_breach(_summary(100.0, 99.8), _LIMITS) is True


def test_check_sla_breach_within_targets():
    assert check_sla_breach(_summary(200.0, 99.95), _LIMITS) is False


def test_both_measures_past_their_limits_are_both_named():
    assert breached(_summary(9999.0, 50.0), _LIMITS) == {
        LATENCY: (9999.0, 5000.0),
        AVAILABILITY: (50.0, 99.9),
    }


def test_an_empty_window_breaches_nothing():
    assert breached({"count": 0, "p99_ms": None, "availability_pct": None}, _LIMITS) == {}


def test_the_limits_are_the_operators_settings(monkeypatch):
    monkeypatch.setenv("PROVISA_SLA_P99_LIMIT_MS", "250")
    monkeypatch.setenv("PROVISA_SLA_AVAILABILITY_MIN_PCT", "95.5")
    assert sla_limits() == SlaLimits(p99_limit_ms=250, availability_min_pct=95.5)
    assert check_sla_breach(_summary(300.0, 100.0)) is True


_ORG = "default"
_T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def record(control_plane):
    return control_plane.org()


async def _served(conn, *queries: tuple[int, int, datetime]) -> None:
    """Audit rows: (duration_ms, status_code, logged_at) each."""
    from sqlalchemy import insert

    from provisa.core.schema_org import query_audit_log

    for duration_ms, status_code, logged_at in queries:
        await conn.execute_core(
            insert(query_audit_log).values(
                tenant_id=_ORG,
                user_id="u",
                role_id="analyst",
                query_hash="h",
                table_ids=[],
                table_names=[],
                source="sql",
                status_code=status_code,
                duration_ms=duration_ms,
                region="local",
                logged_at=logged_at,
            )
        )


async def test_the_summary_is_read_from_the_audit_rows_of_the_window(record):
    async with record.acquire() as conn:
        await _served(
            conn,
            *[(100, 200, _T0 - timedelta(minutes=m)) for m in range(1, 10)],
            (9000, 500, _T0 - timedelta(minutes=5)),
            (1, 200, _T0 - timedelta(hours=2)),  # before the window
        )
        summary = await get_sla_summary(conn, _ORG, now=_T0)
    assert summary["count"] == 10
    assert summary["availability_pct"] == 90.0
    assert summary["p50_ms"] == 100.0
    assert summary["p99_ms"] > 5000


async def test_a_breach_opens_lasts_and_resolves_in_one_row(record):
    from provisa.audit.sla_monitor import list_breaches

    async with record.acquire() as conn:
        bad, good = _summary(9000.0, 100.0), _summary(100.0, 100.0)
        window = {"window_start": _T0.isoformat(), "window_end": _T0.isoformat()}
        opened = await record_evaluation(conn, _ORG, {**bad, **window}, _LIMITS, _T0)
        later = _T0 + timedelta(minutes=5)
        ongoing = await record_evaluation(
            conn, _ORG, {**_summary(7000.0, 100.0), **window}, _LIMITS, later
        )
        # An empty window is no evidence the latency recovered: the breach stays open.
        assert await record_evaluation(conn, _ORG, {"count": 0}, _LIMITS, later) == {}
        resolved_at = _T0 + timedelta(minutes=10)
        resolved = await record_evaluation(conn, _ORG, {**good, **window}, _LIMITS, resolved_at)
        history = await list_breaches(conn, _ORG)
    assert (opened, ongoing, resolved) == (
        {LATENCY: "opened"},
        {LATENCY: "ongoing"},
        {LATENCY: "resolved"},
    )
    (row,) = history
    assert row["kind"] == LATENCY
    assert (row["observed"], row["last_observed"], row["limit"]) == (9000.0, 7000.0, 5000.0)
    assert row["resolved_at"] == resolved_at.isoformat()


def test_each_org_s_evaluation_is_scheduled_once():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from provisa.audit.sla_monitor import register_org_sla, sla_job_id

    scheduler = AsyncIOScheduler()
    register_org_sla(scheduler, "acme")
    job = scheduler.get_job(sla_job_id("acme"))
    register_org_sla(scheduler, "acme")  # a reload keeps the job and its clock
    assert scheduler.get_job(sla_job_id("acme")) is job
    assert job.args == ("acme",)
    assert job.trigger.interval == timedelta(minutes=EVALUATE_MINUTES)


# ---------------------------------------------------------------------------
# export_audit_log — JSON
# ---------------------------------------------------------------------------

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
_START = datetime(2026, 6, 19, 0, 0, 0, tzinfo=timezone.utc)
_END = datetime(2026, 6, 20, 23, 59, 59, tzinfo=timezone.utc)

_FAKE_ROWS = [
    {
        "id": 1,
        "tenant_id": _TENANT_ID,
        "user_id": "alice",
        "role_id": "analyst",
        "query_hash": "abc123",
        "table_ids": ["orders", "customers"],
        "source": "graphql",
        "status_code": 200,
        "duration_ms": 42,
        "logged_at": _NOW,
    }
]


def _make_mock_conn(rows: list[dict]) -> AsyncMock:
    records = []
    for row in rows:
        rec = MagicMock()
        rec._mapping = dict(row)
        records.append(rec)

    result = MagicMock()
    result.fetchall = MagicMock(return_value=records)

    conn = AsyncMock()
    conn.execute_core = AsyncMock(return_value=result)
    return conn


@pytest.mark.asyncio
async def test_export_audit_log_json_valid():
    conn = _make_mock_conn(_FAKE_ROWS)
    result = await export_audit_log(conn, _TENANT_ID, _START, _END, format="json")
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    record = parsed[0]
    assert record["user_id"] == "alice"
    assert record["status_code"] == 200
    assert "logged_at" in record
    assert "query_hash" in record


@pytest.mark.asyncio
async def test_export_audit_log_csv_valid():
    conn = _make_mock_conn(_FAKE_ROWS)
    result = await export_audit_log(conn, _TENANT_ID, _START, _END, format="csv")
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["user_id"] == "alice"
    assert rows[0]["status_code"] == "200"


@pytest.mark.asyncio
async def test_export_audit_log_csv_has_header():
    conn = _make_mock_conn(_FAKE_ROWS)
    result = await export_audit_log(conn, _TENANT_ID, _START, _END, format="csv")
    first_line = result.splitlines()[0]
    assert "user_id" in first_line
    assert "tenant_id" in first_line
    assert "logged_at" in first_line


@pytest.mark.asyncio
async def test_export_audit_log_unsupported_format():
    conn = _make_mock_conn([])
    with pytest.raises(ValueError, match="Unsupported format"):
        await export_audit_log(conn, _TENANT_ID, _START, _END, format="xml")


async def test_the_ops_views_read_the_breaches_and_the_last_hour(record):
    """ops.sla_breach_log is the breach history; ops.service_level the hour the evaluation
    measures, from the same audit rows."""
    from sqlalchemy import text

    from provisa.api._meta_views import _OPS_LOG_TABLE_VIEWS, _OPS_REPORT_VIEWS
    from provisa.api.startup_seed import _adapt_view_ddl

    now = datetime.now(timezone.utc)
    async with record.acquire() as conn:
        await conn.execute(_adapt_view_ddl(_OPS_REPORT_VIEWS["service_level"]))
        await conn.execute(_adapt_view_ddl(_OPS_LOG_TABLE_VIEWS["sla_breach_log"]))

        async def rows(sql):
            return [tuple(r) for r in (await conn.execute_core(text(sql))).fetchall()]

        # An hour with no queries has no service level, rather than a perfect one.
        assert await rows("SELECT * FROM service_level") == []
        await _served(
            conn,
            (100, 200, now - timedelta(minutes=1)),
            (300, 500, now - timedelta(minutes=2)),
            (5, 200, now - timedelta(hours=3)),
        )
        window = {"window_start": now.isoformat(), "window_end": now.isoformat()}
        await record_evaluation(conn, _ORG, {**_summary(9000.0, 50.0), **window}, _LIMITS, now)
        assert await rows(
            "SELECT id, query_count, p50_ms, availability_pct FROM service_level"
        ) == [("last_hour", 2, 200.0, 50.0)]
        assert await rows(
            "SELECT kind, observed, limit_value, resolved_at FROM sla_breach_log_ops ORDER BY kind"
        ) == [(AVAILABILITY, 50.0, 99.9, None), (LATENCY, 9000.0, 5000.0, None)]
