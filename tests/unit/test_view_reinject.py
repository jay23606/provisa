# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A governed statement answered from a fresh view, in the pipeline's optimize stage
(REQ-849, REQ-882, REQ-1586).

Statements here are as the stage sees them: governed, lowered to catalog-physical, with the
aliases any surface gives them. A join-pattern view answers the joins it covers -- fully, or
partly with the other joins kept against it; a junction view answers its two hops with its edge
type; an aggregate view answers a single-table aggregate. A full join match is checked against
the tables on DuckDB.
"""

# Requirements: REQ-849, REQ-882, REQ-1586

from __future__ import annotations

import duckdb
import pytest

from provisa.compiler.sql_types import CompilationContext, TableMeta
from provisa.mv.models import JoinPattern, MVDefinition, MVStatus, TableIdentity
from provisa.mv.view_reinject import reinject

_ORDERS = '"pg"."public"."orders"'
_CUSTOMERS = '"pg"."public"."customers"'
_PAYMENTS = '"pg"."public"."payments"'


def _ctx(*tables: str) -> CompilationContext:
    ctx = CompilationContext()
    for i, name in enumerate(tables):
        ctx.tables[name] = TableMeta(
            table_id=i,
            field_name=name,
            type_name=name.title(),
            source_id="sales-pg",
            catalog_name="pg",
            schema_name="public",
            table_name=name,
            domain_id="sales",
        )
    return ctx


def _join_view(join_type: str = "left", status: MVStatus = MVStatus.FRESH) -> MVDefinition:
    return MVDefinition(
        id="orders_customers",
        source_tables=["orders", "customers"],
        inputs=[
            TableIdentity("sales-pg", "public", "orders"),
            TableIdentity("sales-pg", "public", "customers"),
        ],
        target_catalog="mat",
        target_schema="mv",
        target_table="orders_customers",
        join_pattern=JoinPattern(
            left_table="orders",
            left_column="customer_id",
            right_table="customers",
            right_column="id",
            join_type=join_type,
        ),
        status=status,
    )


_FULL = (
    f'SELECT "o"."id", "c"."name" FROM {_ORDERS} AS "o" '
    f'LEFT JOIN {_CUSTOMERS} AS "c" ON "o"."customer_id" = "c"."id" WHERE "c"."region" = $1'
)


def test_a_join_the_view_covers_reads_the_view_keeping_its_names():
    hit = reinject(_FULL, [_join_view()], _ctx("orders", "customers"))
    assert hit is not None and hit.match == "full"
    assert hit.sql == (
        'SELECT "o"."id" AS "id", "o"."customers__name" AS "name" '
        'FROM "mat"."mv"."orders_customers" '
        'AS "o" WHERE "o"."customers__region" = $1'
    )


def test_a_join_it_covers_among_others_keeps_the_others_against_the_view():
    sql = (
        f'SELECT "o"."id", "c"."name", "p"."amount" FROM {_ORDERS} AS "o" '
        f'LEFT JOIN {_CUSTOMERS} AS "c" ON "o"."customer_id" = "c"."id" '
        f'LEFT JOIN {_PAYMENTS} AS "p" ON "o"."id" = "p"."order_id"'
    )
    hit = reinject(sql, [_join_view()], _ctx("orders", "customers", "payments"))
    assert hit is not None and hit.match == "partial"
    assert f'LEFT JOIN {_PAYMENTS} AS "p" ON "o"."id" = "p"."order_id"' in hit.sql
    assert '"o"."customers__name" AS "name"' in hit.sql and '"p"."amount"' in hit.sql
    assert "customers" not in hit.sql.replace("customers__", "").replace("orders_customers", "")


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        (_FULL.replace("LEFT JOIN", "JOIN"), "an inner join of a left-join view"),
        (_FULL.replace('"o"."id", "c"."name"', "*"), "a star"),
        (_FULL.replace('"o"."id"', '"id"'), "an unqualified column"),
        (_FULL.replace('"o"."customer_id" = "c"."id"', '"o"."id" = "c"."id"'), "another key"),
        (f'SELECT "o"."id" FROM {_ORDERS} AS "o"', "no join"),
    ],
)
def test_a_join_the_view_does_not_cover_exactly_is_left_alone(sql, why):
    assert reinject(sql, [_join_view()], _ctx("orders", "customers")) is None, why


def test_an_inner_join_view_answers_from_either_end():
    sql = (
        f'SELECT "c"."name", "o"."id" FROM {_CUSTOMERS} AS "c" '
        f'JOIN {_ORDERS} AS "o" ON "c"."id" = "o"."customer_id"'
    )
    hit = reinject(sql, [_join_view("inner")], _ctx("orders", "customers"))
    assert hit is not None
    assert '"c"."customers__name" AS "name"' in hit.sql and '"c"."id" AS "id"' in hit.sql


def test_a_view_over_tables_the_role_cannot_name_does_not_answer():
    assert reinject(_FULL, [_join_view()], _ctx("orders")) is None


# -- a junction edge -------------------------------------------------------------------------------


def _junction_view(type_value: str | None = "bonded pair") -> MVDefinition:
    return MVDefinition(
        id="bonded_pair",
        source_tables=["pets", "pet_companions"],
        inputs=[
            TableIdentity("sales-pg", "public", "pets"),
            TableIdentity("sales-pg", "public", "pet_companions"),
        ],
        target_catalog="mat",
        target_schema="mv",
        target_table="bonded_pair",
        join_pattern=JoinPattern(
            left_table="pets",
            left_column="id",
            right_table="pets",
            right_column="id",
            via_table="pet_companions",
            via_left_column="pet_id",
            via_right_column="companion_pet_id",
            via_type_column="relation_type" if type_value else None,
            via_type_value=type_value,
        ),
        status=MVStatus.FRESH,
    )


_TRAVERSAL = (
    'SELECT "a"."name", "e"."since", "b"."name" AS "companion" FROM "pg"."public"."pets" AS "a" '
    'LEFT JOIN "pg"."public"."pet_companions" AS "e" ON "a"."id" = "e"."pet_id" '
    'LEFT JOIN "pg"."public"."pets" AS "b" ON "e"."companion_pet_id" = "b"."id" '
    'WHERE "e"."relation_type" = \'bonded pair\''
)


def test_a_junction_traversal_of_the_views_edge_type_reads_the_view():
    hit = reinject(_TRAVERSAL, [_junction_view()], _ctx("pets", "pet_companions"))
    assert hit is not None and hit.match == "full"
    assert "JOIN" not in hit.sql
    assert '"a"."pets__name" AS "companion"' in hit.sql
    assert '"a"."pet_companions__since" AS "since"' in hit.sql


def test_another_edge_type_does_not_read_the_view():
    sql = _TRAVERSAL.replace("'bonded pair'", "'littermate'")
    assert reinject(sql, [_junction_view()], _ctx("pets", "pet_companions")) is None


# -- what a full join match answers, against the tables --------------------------------------------


def test_a_view_answers_a_join_as_its_tables_do():
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS pg")
    con.execute("CREATE SCHEMA pg.public")
    con.execute("CREATE TABLE pg.public.orders (id INT, customer_id INT, amount INT)")
    con.execute("CREATE TABLE pg.public.customers (id INT, name VARCHAR, region VARCHAR)")
    con.execute(
        "INSERT INTO pg.public.orders VALUES (1, 10, 5), (2, 10, 7), (3, 11, 9), (4, 99, 1)"
    )
    con.execute("INSERT INTO pg.public.customers VALUES (10, 'ann', 'us'), (11, 'bo', 'eu')")
    con.execute("ATTACH ':memory:' AS mat")
    con.execute("CREATE SCHEMA mat.mv")
    con.execute(
        "CREATE TABLE mat.mv.orders_customers AS SELECT orders.*, customers.id AS customers__id, "
        "customers.name AS customers__name, customers.region AS customers__region "
        "FROM pg.public.orders AS orders LEFT JOIN pg.public.customers AS customers "
        "ON orders.customer_id = customers.id"
    )
    sql = (
        f'SELECT "c"."region", SUM("o"."amount") AS "total" FROM {_ORDERS} AS "o" '
        f'LEFT JOIN {_CUSTOMERS} AS "c" ON "o"."customer_id" = "c"."id" GROUP BY "c"."region"'
    )
    hit = reinject(sql, [_join_view()], _ctx("orders", "customers"))
    assert hit is not None
    assert sorted(con.execute(hit.sql).fetchall(), key=str) == sorted(
        con.execute(sql).fetchall(), key=str
    )
