# Copyright (c) 2026 Kenneth Stott
# Canary: 4e8b2c7d-6a1f-4d93-b0e5-9c3f7a2d1e68
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Positional drivers get their values in placeholder-OCCURRENCE order (REQ-589): a client's SQL
may repeat or reorder $N, which binding the list as-is got wrong."""

# Requirements: REQ-589

import pytest

from provisa.compiler.params import bind_positionally


def test_in_order_placeholders_keep_their_order():
    assert bind_positionally("a = $1 AND b = $2", [1, 2], "?") == ("a = ? AND b = ?", [1, 2])


def test_out_of_order_placeholders_bind_the_right_values():
    assert bind_positionally("a = $2 AND b = $1", [1, 2], "?") == ("a = ? AND b = ?", [2, 1])


def test_a_repeated_placeholder_binds_its_value_each_time():
    assert bind_positionally("a = $1 OR b = $1", ["x"], "%s") == ("a = %s OR b = %s", ["x", "x"])


def test_ten_is_not_read_as_one():
    params = list(range(1, 11))
    sql, bound = bind_positionally("a = $10 AND b = $1", params, "?")
    assert (sql, bound) == ("a = ? AND b = ?", [10, 1])


def test_occurrence_numbered_placeholders_for_oracle():
    assert bind_positionally("a = $1 OR b = $1", [5], lambda k: f":{k}") == (
        "a = :1 OR b = :2",
        [5, 5],
    )


def test_a_placeholder_without_a_value_is_refused():
    with pytest.raises(ValueError, match=r"\$2 has no bound value"):
        bind_positionally("a = $2", [1], "?")


def test_no_params_leaves_the_sql_alone():
    assert bind_positionally("a = 'x%'", None, "%s") == ("a = 'x%'", [])


def test_values_with_no_placeholder_to_bind_them_are_refused():
    """A statement written with the driver's own `?` binds none of the values given: SQL Server
    ran it with none and answered "07002 COUNT field incorrect" (generic-rdbms sqlserver)."""
    with pytest.raises(ValueError, match="no \\$N placeholder"):
        bind_positionally("SELECT 1 WHERE a = ?", ["dbo"], "?")


async def test_sql_server_listings_bind_their_schema():
    """Every SQL Server listing statement is written with `$N`, which SQLServerDriver binds."""
    from types import SimpleNamespace

    from provisa.api.admin import introspect

    bound: list[tuple[str, list]] = []

    class _Pool:
        def has(self, _sid):
            return True

        async def execute(self, _sid, sql, params=None):
            bound.append(bind_positionally(sql, params, "?"))
            return SimpleNamespace(rows=[])

    await introspect._native_tables_rdbms("ss", "sqlserver", "dbo", _Pool())
    await introspect.native_columns("ss", "sqlserver", "dbo", "widgets", _Pool())
    statement, _ = introspect._SCHEMA_COLUMNS_SQL["sqlserver"]
    await _Pool().execute("ss", statement, ["dbo"])

    assert [params for _sql, params in bound] == [["dbo"], ["dbo", "widgets"], ["dbo"]]
