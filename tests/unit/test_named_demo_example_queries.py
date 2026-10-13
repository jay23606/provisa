# Copyright (c) 2026 Kenneth Stott
# Canary: dd7c6c21-0d45-45e3-ab17-2a35e67438cc
#
# This source code is licensed under the Business Source License 1.1
"""REQ-2009: a named demo's example GraphQL queries reach the UI on /setup/status, and every one
shipped is valid against the demo's views."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from graphql import parse, validate

from provisa.core import demo

_WEBLOGS = Path(__file__).resolve().parents[2] / "demo" / "named" / "weblogs"


def test_a_named_demo_s_queries_are_read_in_file_name_order(tmp_path, monkeypatch):
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "2-b.graphql").write_text("query B { b }")
    (tmp_path / "queries" / "1-a.graphql").write_text("query A { a }")
    (tmp_path / "queries" / "notes.md").write_text("not a query")
    monkeypatch.setenv(demo.NAMED_DEMO_DIR_ENV, str(tmp_path))
    assert demo.example_queries() == [
        {"name": "1-a", "query": "query A { a }"},
        {"name": "2-b", "query": "query B { b }"},
    ]


def test_no_named_demo_ships_no_queries(tmp_path, monkeypatch):
    monkeypatch.delenv(demo.NAMED_DEMO_DIR_ENV, raising=False)
    assert demo.example_queries() == []
    monkeypatch.setenv(demo.NAMED_DEMO_DIR_ENV, str(tmp_path))  # a demo with no queries/
    assert demo.example_queries() == []


async def test_the_setup_status_carries_them(tmp_path, monkeypatch):
    from provisa.api import setup_router

    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "1-a.graphql").write_text("query A { a }")
    monkeypatch.setenv(demo.NAMED_DEMO_DIR_ENV, str(tmp_path))

    async def state():
        return {"needs_setup": False, "demo_mode": True}

    monkeypatch.setattr(setup_router, "_setup_state", state)
    assert await setup_router.setup_status() == {
        "needs_setup": False,
        "demo_mode": True,
        "named_demo": tmp_path.name,
        "example_queries": [{"name": "1-a", "query": "query A { a }"}],
        "demo_tour": [],
    }


def _weblogs_views_schema():
    """The GraphQL schema the analyst is served for the weblogs demo's views, built from the
    demo's own config as the server builds it (the views' declared columns and types)."""
    from provisa.compiler import naming
    from provisa.compiler.introspect import ColumnMetadata
    from provisa.compiler.schema_gen import SchemaInput, generate_schema
    from provisa.core.config_loader import views_as_tables

    config = views_as_tables(yaml.safe_load((_WEBLOGS / "config.yaml").read_text()))
    views = [t for t in config["tables"] if "view_sql" in t]
    tables, column_types = [], {}
    for i, view in enumerate(views, start=1):
        tables.append(
            {
                "id": i,
                "source_id": view["source_id"],
                "domain_id": view["domain_id"],
                "schema_name": view["schema"],
                "table_name": view["table"],
                "view_sql": view["view_sql"],
                "enable_aggregates": view["enable_aggregates"],
                "enable_group_by": view["enable_group_by"],
                "columns": [
                    {"column_name": c["name"], "visible_to": c["visible_to"]}
                    for c in view["columns"]
                ],
                "write_ops": [],
                "write_returns_rows": False,
                "write_refused_forms": [],
            }
        )
        column_types[i] = [
            ColumnMetadata(column_name=c["name"], data_type=c["data_type"], is_nullable=True)
            for c in view["columns"]
        ]
    (role,) = [r for r in config["roles"] if r["id"] == "analyst"]
    naming.configure(gql="apollo_graphql")
    return generate_schema(
        SchemaInput(
            tables=tables,
            relationships=[],
            column_types=column_types,
            naming_rules=[],
            role=role,
            domains=config["domains"],
            domain_prefix=config["naming"]["domain_prefix"],
        )
    )


QUERIES = sorted((_WEBLOGS / "queries").glob("*.graphql"))


def test_the_weblogs_demo_ships_one_example_a_view():
    assert len(QUERIES) == 6


@pytest.mark.parametrize("path", QUERIES, ids=[p.stem for p in QUERIES])
def test_each_weblogs_example_is_valid_against_the_demo_s_views(path):
    # That each runs and answers rows is tests/integration/test_weblogs_demo.py's, on the demo.
    errors = validate(_weblogs_views_schema(), parse(path.read_text()))
    assert errors == [], [e.message for e in errors]
