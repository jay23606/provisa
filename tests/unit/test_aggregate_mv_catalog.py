# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An aggregate query answered from a view that pre-aggregates its table (REQ-198, REQ-882).

What a view keeps is derived from its SQL; a query is rewritten only when the view answers it
exactly. Each rewrite is checked against the base table on DuckDB: the same statement, read
from the table and from the view built from the view's own SQL, gives the same rows.
"""

# Requirements: REQ-198, REQ-882

from __future__ import annotations

import duckdb
import pytest

from provisa.mv.aggregate_catalog import derive_shape, rewrite_aggregate_query, rewrite_over
from provisa.mv.models import MVDefinition, MVStatus

_RELATION = ("sales_pg", "public", "orders")
_VIEW_SQL = (
    'SELECT "region", "status", COUNT(*) AS "n", SUM("amount") AS "total", '
    'COUNT("amount") AS "n_amount", MIN("amount") AS "low", MAX("amount") AS "high" '
    'FROM "sales_pg"."public"."orders" GROUP BY "region", "status"'
)
_STORED = '"mat"."mv"."orders_rollup"'
_ROWS = [
    ("us", "open", 10),
    ("us", "open", 30),
    ("us", "shipped", 5),
    ("eu", "open", None),
    ("eu", "shipped", 7),
    ("eu", "shipped", 8),
]


def _rollup():
    shape = derive_shape(_VIEW_SQL)
    assert shape is not None
    return shape


# -- what a view keeps ----------------------------------------------------------------------------


def test_a_single_table_group_by_of_storable_aggregates_is_a_rollup():
    shape = derive_shape(_VIEW_SQL)
    assert shape is not None
    assert shape.relation == _RELATION
    assert shape.dims == {"region": "region", "status": "status"}
    assert shape.measures == {
        ("count", "*"): "n",
        ("sum", "amount"): "total",
        ("count", "amount"): "n_amount",
        ("min", "amount"): "low",
        ("max", "amount"): "high",
    }


@pytest.mark.parametrize(
    "sql",
    [
        # AVG cannot be re-aggregated; a view that stores it serves nothing.
        'SELECT "region", AVG("amount") AS "a" FROM "c"."public"."orders" GROUP BY "region"',
        'SELECT "region", COUNT(DISTINCT "amount") AS "d" FROM "c"."public"."orders" GROUP BY "region"',
        # An unnamed aggregate has no column to read it back by.
        'SELECT "region", SUM("amount") FROM "c"."public"."orders" GROUP BY "region"',
        # A filtered view holds only some rows.
        'SELECT "region", SUM("amount") AS "t" FROM "c"."public"."orders" WHERE "status" = \'open\' '
        'GROUP BY "region"',
        'SELECT "o"."region", SUM("o"."amount") AS "t" FROM "c"."public"."orders" "o" '
        'JOIN "c"."public"."lines" "l" ON "o"."id" = "l"."order_id" GROUP BY "o"."region"',
        'SELECT "region", SUM("amount" * 2) AS "t" FROM "c"."public"."orders" GROUP BY "region"',
        'SELECT "id" FROM "c"."public"."orders"',
    ],
)
def test_anything_else_keeps_nothing_a_query_could_use(sql):
    assert derive_shape(sql) is None


# -- what is rewritten, checked against the table ------------------------------------------------


@pytest.fixture(scope="module")
def db():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA public")
    con.execute('CREATE TABLE public.orders ("region" VARCHAR, "status" VARCHAR, "amount" INTEGER)')
    con.executemany("INSERT INTO public.orders VALUES (?, ?, ?)", _ROWS)
    con.execute("ATTACH ':memory:' AS mat")
    con.execute("CREATE SCHEMA mat.mv")
    view = _VIEW_SQL.replace('"sales_pg"."public"."orders"', "public.orders")
    con.execute(f"CREATE TABLE mat.mv.orders_rollup AS {view}")
    yield con
    con.close()


def _rows(db, sql: str, params: list) -> list[tuple]:
    duck = sql.replace("$1", "?").replace("$2", "?")
    return sorted(
        tuple(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v for v in r)
        for r in db.execute(duck, params).fetchall()
    )


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ('SELECT COUNT(*), SUM("amount"), MIN("amount"), MAX("amount") FROM "public"."orders"', []),
        ('SELECT "region", COUNT(*), COUNT("amount") FROM "public"."orders" GROUP BY "region"', []),
        (
            'SELECT "region", SUM("amount"), AVG("amount") FROM "public"."orders" '
            'WHERE "status" = $1 GROUP BY "region" ORDER BY SUM("amount") DESC LIMIT $2',
            ["open", 5],
        ),
        ('SELECT "status", MAX("amount") AS "top" FROM "public"."orders" GROUP BY "status"', []),
        # Filtered to nothing: COUNT is 0, as on the table.
        ('SELECT COUNT(*) FROM "public"."orders" WHERE "region" = $1', ["asia"]),
    ],
)
def test_a_rewritten_query_answers_as_the_table_does(db, sql, params):
    rewritten = rewrite_over(sql, _RELATION, _rollup(), _STORED)
    assert rewritten is not None and "orders_rollup" in rewritten
    assert _rows(db, rewritten, params) == _rows(db, sql, params)


def test_an_unnamed_output_keeps_the_name_postgres_gives_it():
    rewritten = rewrite_over(
        'SELECT "region", COUNT(*), SUM("amount") FROM "public"."orders" GROUP BY "region"',
        _RELATION,
        _rollup(),
        _STORED,
    )
    assert rewritten is not None
    assert 'AS "region"' in rewritten and 'AS "count"' in rewritten and 'AS "sum"' in rewritten


@pytest.mark.parametrize(
    "sql",
    [
        # Filters, groups or reads a column the view does not keep.
        'SELECT SUM("amount") FROM "public"."orders" WHERE "amount" > 3',
        'SELECT "amount", COUNT(*) FROM "public"."orders" GROUP BY "amount"',
        # Asks for what the view cannot re-aggregate.
        'SELECT COUNT(DISTINCT "region") FROM "public"."orders"',
        'SELECT SUM("tax") FROM "public"."orders"',
        'SELECT "region", COUNT(*) FROM "public"."orders" GROUP BY "region" HAVING COUNT(*) > 1',
        'SELECT DISTINCT "region" FROM "public"."orders"',
        'SELECT "region", SUM("amount") OVER () FROM "public"."orders"',
        # Not an aggregate at all.
        'SELECT "region" FROM "public"."orders"',
    ],
)
def test_a_query_the_view_cannot_answer_exactly_is_left_alone(sql):
    assert rewrite_over(sql, _RELATION, _rollup(), _STORED) is None


def test_avg_needs_a_stored_sum_and_count_of_its_column():
    shape = derive_shape(
        'SELECT "region", SUM("amount") AS "t" FROM "sales_pg"."public"."orders" GROUP BY "region"'
    )
    assert (
        rewrite_over('SELECT AVG("amount") FROM "public"."orders"', _RELATION, shape, _STORED)
        is None
    )


# -- which view answers ---------------------------------------------------------------------------


def _mv(mv_id: str, sql: str | None, status: MVStatus = MVStatus.FRESH) -> MVDefinition:
    return MVDefinition(
        id=mv_id,
        source_tables=["orders"],
        target_catalog="mat",
        target_schema="mv",
        target_table=f"{mv_id}_t",
        sql=sql,
        status=status,
    )


def test_the_first_view_over_the_same_table_that_answers_is_used():
    other_table = _mv("lines", _VIEW_SQL.replace('"orders"', '"lines"'))
    sum_only = _mv(
        "sums",
        'SELECT "region", SUM("amount") AS "t" FROM "sales_pg"."public"."orders" GROUP BY "region"',
    )
    rollup = _mv("rollup", _VIEW_SQL)
    hit = rewrite_aggregate_query(
        'SELECT COUNT(*) FROM "public"."orders"', _RELATION, [other_table, sum_only, rollup]
    )
    assert hit is not None
    sql, mv = hit
    assert mv.id == "rollup"
    assert sql.startswith("/* aggregate_mv: rollup */")
    assert '"mat"."mv"."rollup_t"' in sql


def test_no_view_answers_when_none_holds_the_table():
    assert rewrite_aggregate_query('SELECT COUNT(*) FROM "public"."orders"', _RELATION, []) is None
