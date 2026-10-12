# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The real sample a synthetic dataset's closeness is measured over reads a column recorded as a
date or a timestamp, whose source holds it as text (a SQLite date), as its recorded type: seconds
since the epoch. The statement runs against an in-process DuckDB as the pipeline transpiles it."""

# Requirements: REQ-1934

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import sqlglot

from provisa.profiler.statement import ColumnSpec
from provisa.synthetic import closeness
from provisa.synthetic.run import sample_read_sql

_SPECS = [
    ColumnSpec("amount", "DOUBLE", "numeric", "amount"),
    ColumnSpec("visit_date", "DATE", "temporal", "visit_date"),
    ColumnSpec("seen_at", "TIMESTAMP", "temporal", "seen_at"),
    ColumnSpec("reason", "VARCHAR", "text", "reason"),
]


def _epoch(*parts: int) -> float:
    return datetime(*parts, tzinfo=timezone.utc).timestamp()


def test_a_time_held_as_text_enters_the_closeness_sample_as_seconds_since_the_epoch():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA d")
    con.execute(
        "CREATE TABLE d.visits AS SELECT range::DOUBLE AS amount, "
        "strftime(DATE '2025-01-01' + range::INTEGER, '%Y-%m-%d') AS visit_date, "
        "strftime(TIMESTAMP '2025-01-01 08:00:00' + to_seconds(range * 3600), "
        "'%Y-%m-%d %H:%M:%S') AS seen_at, 'r' || range::VARCHAR AS reason FROM range(5)"
    )
    held = dict(con.execute("SELECT column_name, data_type FROM duckdb_columns()").fetchall())
    assert held["visit_date"] == held["seen_at"] == "VARCHAR"
    sql = sqlglot.transpile(sample_read_sql("d.visits", _SPECS), read="postgres", write="duckdb")
    rows = con.execute(sql[0]).fetchall()
    assert len(rows) == min(5, closeness.SAMPLE_ROWS)
    by_amount = {r[0]: r for r in rows}
    assert by_amount[2.0] == (2.0, _epoch(2025, 1, 3), _epoch(2025, 1, 1, 10), "r2")
