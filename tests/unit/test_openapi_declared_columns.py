# Copyright (c) 2026 Kenneth Stott
# Canary: 1c71f00b-584f-4038-849c-adcc2f616e5c
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1924 (amended): a GET whose response declares no row schema is offered as a table whose
columns the steward declares when registering it, for every OpenAPI source. Its endpoint's fields
are those declared columns; registering it with none is refused by name."""

from __future__ import annotations

import pytest

from provisa.api_source.openapi_endpoint import NoDeclaredColumns, endpoint_columns
from provisa.core.models import Column
from provisa.openapi.mapper import parse_spec

_SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "Shelter", "version": "1"},
    "paths": {
        "/kennels/{site}/dogs": {
            "get": {
                "operationId": "listDogs",
                "parameters": [
                    {"name": "site", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "breed", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "the dogs"}},
            }
        }
    },
}


def _query():
    queries, _ = parse_spec(_SPEC)
    (query,) = queries
    return query


def _col(name: str, data_type: str | None, native: str | None = None) -> Column:
    # A parameter column states whether its source requires it: the path parameter does.
    return Column(
        name=name,
        data_type=data_type,
        visible_to=["admin"],
        native_filter_type=native,
        native_filter_required=True if native else None,
    )


def test_the_operation_is_offered_as_a_table_whose_columns_are_declared():
    query = _query()
    assert (query.operation_id, query.columns_declared, query.response_schema) == (
        "listDogs",
        True,
        None,
    )


def test_its_endpoint_reads_the_declared_columns_then_its_parameters():
    declared = [
        _col("name", "text"),
        _col("age", "integer"),
        _col("weight", "double"),
        _col("vaccinated", "boolean"),
        _col("intake", "timestamp"),
        _col("traits", "json"),
        _col("_nf_site", "text", "path_param"),
    ]
    columns = endpoint_columns(_query(), ("dogs", declared))
    assert [(c["name"], c["type"], c.get("param_type")) for c in columns] == [
        ("name", "string", None),
        ("age", "integer", None),
        ("weight", "number", None),
        ("vaccinated", "boolean", None),
        ("intake", "string", None),
        ("traits", "jsonb", None),
        ("site", "string", "path"),
        ("breed", "string", "query"),
    ]


def test_registering_it_with_no_declared_column_is_refused_by_name():
    with pytest.raises(NoDeclaredColumns, match="'dogs': its operation declares no response"):
        endpoint_columns(_query(), ("dogs", [_col("_nf_site", "text", "path_param")]))


def test_an_operation_with_a_response_schema_keeps_its_own_columns():
    spec = {
        **_SPEC,
        "paths": {
            "/dogs": {
                "get": {
                    "operationId": "allDogs",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    (query,), _ = parse_spec(spec)
    assert not query.columns_declared
    assert [c["name"] for c in endpoint_columns(query, ("dogs", [_col("x", "text")]))] == ["id"]


# -- a sample answer suggests columns, and stores nothing ------------------------------------


def test_the_first_rows_fields_are_suggested_by_what_each_value_is():
    from provisa.api.admin._openapi_sample import suggested_columns

    answer = {"result": [{"name": "Rex", "age": 4, "weight": 21.5, "ok": True, "tags": ["a"]}]}
    assert suggested_columns(answer) == [
        ("name", "text"),
        ("age", "bigint"),
        ("weight", "double"),
        ("ok", "boolean"),
        ("tags", "json"),
    ]
    # A string stays text whatever it looks like: nothing is guessed beyond the JSON value.
    assert suggested_columns([{"intake": "2026-10-12T00:00:00Z"}]) == [("intake", "text")]
    assert suggested_columns({"id": 1}) == [("id", "bigint")]
    assert suggested_columns([]) == []


@pytest.mark.asyncio
async def test_the_sample_calls_the_operation_once_with_the_stewards_parameters(monkeypatch):
    from types import SimpleNamespace

    import httpx

    from provisa.api.admin import _openapi_sample

    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=[{"name": "Rex", "age": 4}])

    real = httpx.AsyncClient
    monkeypatch.setattr(
        _openapi_sample.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(answer), **kw),
    )
    state = SimpleNamespace(
        openapi_specs={"shelter": {"spec": _SPEC}},
        api_sources={
            "shelter": SimpleNamespace(base_url="https://shelter.example", auth=None, headers={})
        },
    )
    suggested = await _openapi_sample.sample_columns(
        state, "shelter", "listDogs", {"site": "north", "breed": "collie", "unused": ""}
    )
    assert suggested == [("name", "text"), ("age", "bigint")]
    (request,) = asked
    assert request.url.path == "/kennels/north/dogs"
    assert dict(request.url.params) == {"breed": "collie"}
    with pytest.raises(LookupError, match="needs path parameter 'site'"):
        await _openapi_sample.sample_columns(state, "shelter", "listDogs", {})
