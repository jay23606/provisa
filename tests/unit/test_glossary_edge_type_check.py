# Copyright (c) 2026 Kenneth Stott
# Canary: 8d473481-e740-4458-86ea-0c2f3c1e69ae
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1387: every edge type the glossary offers is one the control plane's check admits.

schema.sql (PostgreSQL) carried the original four types after TERM_EDGE_TYPES grew to ten, so a
config's DERIVED_FROM edge was refused at boot by glossary_term_edges_rel_type_check. Both
spellings of the schema must list exactly TERM_EDGE_TYPES, in the CREATE and in the refresh of a
table that predates the wider set."""

import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from provisa.core.glossary import TERM_EDGE_TYPES
from provisa.core.schema_org import glossary_term_edges

_SCHEMA_SQL = Path(__file__).resolve().parents[2] / "provisa" / "core" / "schema.sql"


def _types_in(check_sql: str) -> set[str]:
    return set(re.findall(r"'([A-Z_]+)'", check_sql))


def test_schema_sql_admits_every_edge_type_in_the_create_and_the_refresh():
    sql = _SCHEMA_SQL.read_text()
    checks = re.findall(
        r"glossary_term_edges_rel_type_check\s+CHECK\s*\(rel_type IN \((.*?)\)\)", sql, re.S
    )
    assert len(checks) == 2, "the CREATE and the refresh each name the check"
    for check in checks:
        assert _types_in(check) == set(TERM_EDGE_TYPES)


def test_portable_schema_admits_every_edge_type():
    (check,) = [
        c
        for c in glossary_term_edges.constraints
        if isinstance(c, CheckConstraint) and c.name == "glossary_term_edges_rel_type_check"
    ]
    assert _types_in(str(check.sqltext)) == set(TERM_EDGE_TYPES)


def _edges_ddl() -> tuple[str, str]:
    """schema.sql's CREATE of glossary_term_edges and its refresh block, as written."""
    sql = _SCHEMA_SQL.read_text()
    create = re.search(r"CREATE TABLE IF NOT EXISTS glossary_term_edges \(.*?\n\);\n", sql, re.S)
    refresh = re.search(
        r"DO \$\$ BEGIN\n    ALTER TABLE glossary_term_edges DROP CONSTRAINT.*?END \$\$;\n",
        sql,
        re.S,
    )
    assert create and refresh
    return create.group(0), refresh.group(0)


def _insert_derived_from(cur) -> None:
    cur.execute("INSERT INTO glossary_terms DEFAULT VALUES RETURNING id")
    a = cur.fetchone()[0]
    cur.execute("INSERT INTO glossary_terms DEFAULT VALUES RETURNING id")
    b = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO glossary_term_edges (from_term_id, to_term_id, rel_type) "
        "VALUES (%s, %s, 'DERIVED_FROM')",
        (a, b),
    )


def test_postgres_admits_derived_from_on_a_fresh_table_and_one_that_predates_it(
    embedded_postgres,
):
    import psycopg

    create, refresh = _edges_ddl()
    with psycopg.connect(embedded_postgres.dsn(), autocommit=True) as conn, conn.cursor() as cur:
        for schema, predates in (("edges_fresh", False), ("edges_old", True)):
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute(f"CREATE SCHEMA {schema}")
            cur.execute(f"SET search_path TO {schema}")
            cur.execute("CREATE TABLE glossary_terms (id SERIAL PRIMARY KEY)")
            if predates:
                # The table as the four-type schema.sql created it.
                cur.execute(
                    "CREATE TABLE glossary_term_edges (id SERIAL PRIMARY KEY, "
                    "from_term_id INTEGER NOT NULL REFERENCES glossary_terms(id), "
                    "to_term_id INTEGER NOT NULL REFERENCES glossary_terms(id), "
                    "rel_type TEXT NOT NULL CHECK (rel_type IN "
                    "('KIND_OF', 'RELATED_TO', 'PART_OF', 'SYNONYM_OF')), tenant_id UUID, "
                    "UNIQUE (from_term_id, to_term_id, rel_type))"
                )
            cur.execute(create)
            cur.execute(refresh)
            cur.execute(refresh)  # a reboot re-runs it
            _insert_derived_from(cur)
            cur.execute(f"DROP SCHEMA {schema} CASCADE")
