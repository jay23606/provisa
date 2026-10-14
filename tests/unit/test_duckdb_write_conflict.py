# Copyright (c) 2026 Kenneth Stott
# Canary: 3ea6df94-9e36-43c8-a2e0-29f23e9db22d
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-2006: a write-write conflict DuckDB raises is refused by name, never retried or swallowed."""

# Requirements: REQ-2006

from __future__ import annotations

import duckdb
import pytest

from provisa.federation.duckdb_runtime import WriteConflict, named_write_conflict


def test_two_transactions_writing_one_row_the_second_is_refused_by_name():
    con = duckdb.connect()
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER)")
    con.execute("INSERT INTO t VALUES (1, 0)")
    first, second = con.cursor(), con.cursor()
    first.execute("BEGIN")
    second.execute("BEGIN")
    first.execute("UPDATE t SET n = 1 WHERE id = 1")
    with pytest.raises(WriteConflict) as refused:
        with named_write_conflict():
            second.execute("UPDATE t SET n = 2 WHERE id = 1")
    assert refused.value.code == "engine.write_conflict"
    first.execute("COMMIT")
    assert con.execute("SELECT n FROM t").fetchall() == [(1,)]


def test_any_other_error_is_left_as_it_is():
    con = duckdb.connect()
    with pytest.raises(duckdb.CatalogException):
        with named_write_conflict():
            con.execute("SELECT * FROM nowhere")
