# Copyright (c) 2026 Kenneth Stott
# Canary: af86653c-16dc-4d87-abc1-d67fe8fefec5
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A column recorded as a date or a timestamp whose source holds it as text (a SQLite date): the
engine reads text, and every profiler statement reads the column as its recorded type (REQ-1934).
The statements run against an in-process DuckDB as the pipeline transpiles them."""

# Requirements: REQ-1934

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest
import sqlglot

from provisa.profiler import dependence as dep
from provisa.profiler.statement import (
    CheckSpec,
    ColumnSpec,
    Sample,
    count_sql,
    parse_profile_result,
    profile_sql,
)

_VISITS = [
    ColumnSpec("id", "integer", "numeric", "id"),
    ColumnSpec("pet_id", "integer", "numeric", "pet_id"),
    ColumnSpec("visit_date", "date", "temporal", "visit_date"),
    ColumnSpec("seen_at", "timestamp", "temporal", "seen_at"),
]
_PETS = dep.ParentSpec(
    relationship="pet",
    table="d.pets",
    table_id=2,
    child_key="pet_id",
    parent_key="id",
    columns=[ColumnSpec("born", "date", "temporal", "born")],
)


def _epoch(d: date | datetime) -> float:
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day)
    return d.replace(tzinfo=timezone.utc).timestamp()


@pytest.fixture
def con():
    db = duckdb.connect()
    db.execute("CREATE SCHEMA d")
    db.execute(
        "CREATE TABLE d.pets AS SELECT range AS id, "
        "strftime(DATE '2020-01-01' + range::INTEGER * 30, '%Y-%m-%d') AS born FROM range(10)"
    )
    db.execute(
        "CREATE TABLE d.visits AS SELECT range::INTEGER AS id, range % 10 AS pet_id, "
        "strftime(DATE '2025-01-01' + range::INTEGER, '%Y-%m-%d') AS visit_date, "
        "strftime(TIMESTAMP '2025-01-01 08:00:00' + to_seconds(range * 3600), "
        "'%Y-%m-%d %H:%M:%S') AS seen_at FROM range(100)"
    )
    held = dict(db.execute("SELECT column_name, data_type FROM duckdb_columns()").fetchall())
    assert held["visit_date"] == held["seen_at"] == held["born"] == "VARCHAR"
    return db


def _run(con, sql: str):
    res = con.execute(sqlglot.transpile(sql, read="postgres", write="duckdb")[0])
    return [d[0] for d in res.description], res.fetchall()


def test_a_date_held_as_text_is_profiled_as_a_date(con):
    sql = profile_sql("d.visits", _VISITS, [], Sample("whole"), 100, [], [])
    agg = parse_profile_result(*_run(con, sql), _VISITS, [], [], [])
    by = {c.spec.name: c for c in agg.columns}
    visit = by["visit_date"]
    assert (visit.vmin, visit.vmax) == (_epoch(date(2025, 1, 1)), _epoch(date(2025, 4, 10)))
    assert (visit.min_text, visit.max_text) == ("2025-01-01", "2025-04-10")
    seen = by["seen_at"]
    assert (seen.vmin, seen.vmax) == (
        _epoch(datetime(2025, 1, 1, 8)),
        _epoch(datetime(2025, 1, 5, 11)),
    )


def test_a_range_constraint_on_a_date_held_as_text_counts_the_rows_outside_it(con):
    check = CheckSpec(
        "range", "visit_date", low=_epoch(date(2025, 1, 1)), high=_epoch(date(2025, 1, 31))
    )
    sql = profile_sql("d.visits", _VISITS, [], Sample("whole"), 100, [], [check])
    agg = parse_profile_result(*_run(con, sql), _VISITS, [], [], [check])
    assert agg.violations == [69]


def test_the_latest_watermark_held_as_text_is_read_as_a_time(con):
    _, rows = _run(con, count_sql("d.visits", _VISITS[3]))
    assert (rows[0][0], float(rows[0][1])) == (100, _epoch(datetime(2025, 1, 5, 11)))


def test_dates_held_as_text_enter_the_dependence_measures_as_numbers(con):
    own = list(zip(_VISITS, [100, 10, 100, 100], [1.0] * 4))
    born_counts = {"born": (10, 1.0)}
    cols = dep.choose_columns(
        own, [(_PETS, born_counts)], max_numbers=20, max_distinct=20, max_categories=10
    )
    assert {c.name for c in cols} == {"id", "pet_id", "visit_date", "seen_at", "pet.born"}
    sql = dep.pairs_sql("d.visits", _VISITS, [_PETS], cols, Sample("whole"))
    pairs = dep.parse_pairs(*_run(con, sql), cols)
    by = {(cols[a].name, cols[b].name): s for (a, b), s in pairs.items()}
    assert dep.spearman(by[("visit_date", "seen_at")]) == pytest.approx(1.0)
    assert dep.spearman(by[("pet_id", "pet.born")]) == pytest.approx(1.0)
