# Copyright (c) 2026 Kenneth Stott
# Canary: c2e7b049-6a13-4f8d-9b5e-0d4a8f1c7e62
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1965: registration settles each column against what it natively is at its source. A
natively array, struct or map column is recorded with its hidden attributes, from the source and
never from the caller; registering one as any other type is refused by name."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provisa.api.admin import _table_ops, schema_query
from provisa.api.admin.types import AvailableColumnType
from provisa.core.models import Column

_INPUT = SimpleNamespace(
    source_id="orders-pg", schema_name="public", table_name="orders", query_template=None
)


class _Pool:
    def acquire(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _source(monkeypatch, listed: list[AvailableColumnType], stored: dict[str, str]) -> list:
    """The source lists ``listed``; the table already stores ``stored``. Returns the calls made
    to the source."""
    asked: list[tuple] = []

    async def _meta(source_id, schema_name, table_name):
        asked.append((source_id, schema_name, table_name))
        return listed

    async def _stored(_conn, _source_id, _schema, _table):
        return stored

    monkeypatch.setattr(schema_query, "resolve_available_columns_metadata", _meta)
    monkeypatch.setattr("provisa.core.repositories.table.stored_column_types", _stored)
    return asked


def _tags(platform: str = "postgresql") -> AvailableColumnType:
    return AvailableColumnType(
        name="tags",
        data_type="json",
        comment=None,
        array_depth=1,
        element_type="text",
        native_type="text[]",
        native_platform=platform,
    )


async def test_a_native_array_column_is_recorded_with_what_the_source_states(monkeypatch):
    _source(monkeypatch, [_tags()], stored={})
    columns = [Column(name="tags", data_type="json", visible_to=[])]

    assert await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns) is None

    tags = columns[0]
    assert (tags.array_depth, tags.element_type, tags.native_type, tags.native_platform) == (
        1,
        "text",
        "text[]",
        "postgresql",
    )


@pytest.mark.parametrize("declared", ["text", "varchar", "jsonb"])
async def test_a_native_array_column_registered_as_another_type_is_refused_by_name(
    monkeypatch, declared
):
    _source(monkeypatch, [_tags()], stored={})
    columns = [Column(name="tags", data_type=declared, visible_to=[])]

    refused = await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns)

    assert refused is not None and refused.success is False
    assert refused.code == "schema.column_natively_nested"
    assert refused.params == {"column": "tags", "native_type": "text[]", "type": declared}
    assert columns[0].native_type is None


async def test_a_column_that_is_json_at_its_source_carries_no_attribute(monkeypatch):
    doc = AvailableColumnType(name="doc", data_type="json", comment=None)
    _source(monkeypatch, [doc], stored={})
    columns = [Column(name="doc", data_type="json", visible_to=[])]

    assert await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns) is None

    assert (columns[0].array_depth, columns[0].native_type) == (0, None)


async def test_a_column_kept_as_registered_does_not_ask_the_source(monkeypatch):
    """Editing a table does not depend on its source being reachable: only a new column, or one
    whose type is changed, is settled against the source."""
    asked = _source(monkeypatch, [_tags()], stored={"tags": "json", "id": "integer"})
    columns = [
        Column(name="id", data_type="integer", visible_to=[]),
        Column(name="tags", data_type="json", visible_to=[]),
    ]

    assert await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns) is None
    assert asked == []

    columns[1].data_type = "text"  # an edit that retypes the stored column
    refused = await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns)
    assert refused is not None and refused.code == "schema.column_natively_nested"
    assert len(asked) == 1


async def test_a_native_type_the_engine_listed_is_recorded_as_the_engines_spelling(monkeypatch):
    """A PostgreSQL ``text[]`` the bound Trino lists is spelled ``array(varchar)``. That is
    Trino's spelling, and is recorded as Trino's: a cast into it may run on Trino only."""

    async def _listed_by_the_engine(_source_id, _schema, _table):
        return [
            AvailableColumnType(name="id", data_type="integer", comment=None),
            AvailableColumnType(name="tags", data_type="array(varchar)", comment=None),
        ]

    state = SimpleNamespace(
        source_types={"orders-pg": "postgresql"},
        federation_engine=SimpleNamespace(engine=SimpleNamespace(dialect="trino")),
    )
    monkeypatch.setattr("provisa.api.app.state", state)
    monkeypatch.setattr(schema_query, "_introspect_available_columns", _listed_by_the_engine)

    columns = await schema_query.resolve_available_columns_metadata("orders-pg", "public", "orders")

    tags = columns[1]
    assert (tags.data_type, tags.array_depth, tags.element_type) == ("json", 1, "text")
    assert (tags.native_type, tags.native_platform) == ("array(varchar)", "trino")
    assert columns[0].native_platform is None


async def test_an_embedding_column_stays_the_native_array_a_similarity_search_reads(monkeypatch):
    """REQ-424: an embedding is exempt from the JSON rule end to end: registered as the array it
    is, with no hidden attribute, so no read converts it to JSON."""
    vec = AvailableColumnType(
        name="vec",
        data_type="json",
        comment=None,
        array_depth=1,
        element_type="double",
        native_type="double precision[]",
        native_platform="postgresql",
    )
    asked = _source(monkeypatch, [vec], stored={})
    columns = [
        Column(
            name="vec",
            data_type="array(double)",
            visible_to=[],
            embedding=True,
            embedding_model="mini",
        )
    ]

    assert await _table_ops._settle_nested_columns(_Pool(), _INPUT, columns) is None
    assert (columns[0].data_type, columns[0].native_type, columns[0].array_depth) == (
        "array(double)",
        None,
        0,
    )
    assert asked == []


async def test_a_table_its_query_produces_is_not_listed_from_the_source(monkeypatch):
    """A neo4j table's columns are what its Cypher returns, typed by the preview: registering it
    asked the source for a listing a query-API source has no driver or engine attach for, and
    registerTable failed "cannot list the columns of source 'neo4j_ui_it'"."""
    asked = _source(monkeypatch, [], stored={})
    neo4j = SimpleNamespace(
        source_id="neo4j_ui_it",
        schema_name="neo4j",
        table_name="adopters",
        query_template="MATCH (a:Adopter) RETURN a.id AS adopter_id, a.name AS name",
    )
    columns = [
        Column(name="adopter_id", data_type="integer", visible_to=[]),
        Column(name="name", data_type="text", visible_to=[]),
    ]

    assert await _table_ops._settle_nested_columns(_Pool(), neo4j, columns) is None
    assert asked == []


async def test_a_checkers_result_table_is_not_listed_from_its_source(monkeypatch):
    """A Soda or Great Expectations result table's columns are the checker's result envelope
    (REQ-1443), which Provisa writes; the checker source has no listing of them, and registering
    one failed "cannot list the columns of source 'dq-soda'" (core e2e lane, 87d09e9c5)."""
    asked = _source(monkeypatch, [], stored={})
    checker = SimpleNamespace(
        source_id="dq-soda",
        schema_name="main",
        table_name="orders_rows_soda_dq_dq",
        query_template=None,
        dq_contract="dataset: provisa/sales/orders\nchecks:\n  - row_count > 0\n",
    )
    columns = [Column(name="outcome", data_type="text", visible_to=[])]
    assert await _table_ops._settle_nested_columns(_Pool(), checker, columns) is None
    assert asked == []
