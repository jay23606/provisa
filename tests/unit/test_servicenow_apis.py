# Copyright (c) 2026 Kenneth Stott
# Canary: 650eae93-2dd0-4d84-9819-1b2560906a74
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A ServiceNow instance's own APIs (REQ-1954), read from what it publishes: its API list and
each API's OpenAPI document, recorded from a test instance (tests/fixtures/servicenow)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from provisa.openapi import servicenow as sn
from provisa.openapi.mapper import UNTYPED_BODY, parse_spec

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "servicenow"
_URL = "https://acme.service-now.com"


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def instance(monkeypatch):
    """The instance's answers, from the recorded fixtures; every call is kept."""
    calls: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/now/doc":
            return httpx.Response(200, json=_fixture("doc_catalog.json"))
        name = request.url.params.get("name")
        recorded = {
            "Import Set API": "oas_import_set_api.json",
            "Service Catalog API": "oas_service_catalog_api.json",
        }
        if name in recorded:
            return httpx.Response(200, json=_fixture(recorded[name]))
        return httpx.Response(404, json={"error": {"message": "Not Found"}, "status": "failure"})

    real = httpx.Client

    def client(**kw):
        return real(transport=httpx.MockTransport(answer), **kw)

    monkeypatch.setattr(sn.httpx, "Client", client)
    return calls


def test_the_instances_apis_are_listed_by_namespace_and_name(instance):
    apis = sn.list_instance_apis(_URL, "admin", "pw")
    assert [(a.namespace, a.name, a.route) for a in apis] == [
        ("now", "Import Set API", "now/import"),
        ("now", "Table API", "now/table"),
        ("sn_sc", "Service Catalog API", "sn_sc/servicecatalog"),
    ]
    assert instance[0].headers["Authorization"].startswith("Basic ")


def test_an_apis_document_is_the_one_the_explorer_exports(instance):
    spec = sn.fetch_api_spec(_URL, "admin", "pw", "now", "Import Set API")
    asked = instance[0].url
    assert asked.path == "/api/now/doc/oas_3"
    assert dict(asked.params) == {
        "namespace": "now",
        "name": "Import Set API",
        "format": "json",
        "version": "latest",
    }
    assert "/api/now/import/{stagingTableName}" in spec["paths"]


def test_an_api_the_instance_does_not_export_is_refused_by_name(instance):
    with pytest.raises(sn.InstanceApiError, match="HTTP 404"):
        sn.fetch_api_spec(_URL, "admin", "pw", "now", "No Such API")


def test_the_merged_document_offers_each_apis_operations_at_the_instance(instance):
    specs = [
        sn.fetch_api_spec(_URL, "admin", "pw", "now", "Import Set API"),
        sn.fetch_api_spec(_URL, "admin", "pw", "sn_sc", "Service Catalog API"),
    ]
    merged = sn.merged_spec("helpdesk APIs", _URL, specs)
    assert merged["servers"] == [{"url": _URL}]
    queries, mutations = parse_spec(merged)
    paths = {(m.method, m.path) for m in mutations}
    assert ("POST", "/api/now/import/{stagingTableName}") in paths
    assert ("POST", "/api/sn_sc/servicecatalog/cart/submit_order") in paths
    # The instance's bodies declare no schema: each is one untyped body.
    create = next(m for m in mutations if m.path == "/api/now/import/{stagingTableName}")
    assert create.input_schema == UNTYPED_BODY
    # Its GET operations declare no response schema: each is a command that reads (REQ-1924),
    # not a table, since nothing says what its rows hold.
    assert queries == []
    reads = {m.path for m in mutations if m.reads}
    assert "/api/sn_sc/servicecatalog/cart" in reads


def test_two_apis_declaring_one_path_are_refused(instance):
    spec = sn.fetch_api_spec(_URL, "admin", "pw", "now", "Import Set API")
    with pytest.raises(sn.InstanceApiError, match="declared by two"):
        sn.merged_spec("x", _URL, [spec, spec])
