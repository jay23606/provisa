# Copyright (c) 2026 Kenneth Stott
# Canary: 1cabcb05-0ba1-4a92-ad10-0f9c598f847b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An operation that declares a JSON request body without its schema is still offered with its
one ``body`` argument, a JSON object sent as given (REQ-1954), for every OpenAPI source."""

from __future__ import annotations

from provisa.openapi.mapper import UNTYPED_BODY, parse_spec


def _spec(request_body: dict | None) -> dict:
    operation: dict = {"operationId": "createNote", "responses": {"201": {"description": "made"}}}
    if request_body is not None:
        operation["requestBody"] = request_body
    return {
        "openapi": "3.0.1",
        "info": {"title": "Notes", "version": "1"},
        "paths": {
            "/notes/{book}": {
                "post": {
                    **operation,
                    "parameters": [{"name": "book", "in": "path", "required": True, "schema": {}}],
                }
            }
        },
    }


def _mutation(request_body: dict | None):
    _queries, mutations = parse_spec(_spec(request_body))
    (mutation,) = mutations
    return mutation


def test_a_json_body_declared_without_a_schema_is_one_untyped_object():
    mutation = _mutation({"content": {"application/json": {}, "application/xml": {}}})
    assert mutation.input_schema == UNTYPED_BODY == {"type": "object"}
    assert not mutation.form and not mutation.multipart


def test_a_json_body_with_a_schema_keeps_its_fields():
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    mutation = _mutation({"content": {"application/json": {"schema": schema}}})
    assert mutation.input_schema["properties"] == {"text": {"type": "string"}}


def test_an_operation_with_no_json_body_has_no_body():
    assert _mutation(None).input_schema is None
    assert _mutation({"content": {"application/xml": {}}}).input_schema is None


def test_the_untyped_body_is_offered_as_the_body_argument():
    from types import SimpleNamespace

    from provisa.executor import source_operation as so

    spec = _spec({"content": {"application/json": {}}})
    state = SimpleNamespace(
        openapi_specs={"notes": {"spec": spec}},
        source_types={"notes": "openapi"},
    )
    (operation,) = so._openapi_operations(state, "notes")
    assert so.BODY_ARGUMENT in operation.arguments
