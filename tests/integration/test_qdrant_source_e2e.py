# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""E2E: Qdrant as a source (REQ-1983), on the qdrant/qdrant image.

Everything here is the ``test`` instance: a Qdrant this module starts on a leased port and
removes, an embeddings endpoint it serves itself (OpenAI-compatible, a fixed vector per word),
and an isolated DuckDB server. Tables:

* ``docs``: a collection table read whole, its point id the key;
* ``docs_search``: a search over ``docs``' named vector ``text``, its query a required argument,
  ``lang`` an optional argument in its filter, ``k`` its limit;
* ``docs_by_text``: the same search with an embedding model, so a text query is embedded first.
"""

# Requirements: REQ-1983
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import yaml

pytestmark = [pytest.mark.integration]

_ROLE = "org_admin"
_IMAGE = "qdrant/qdrant:v1.12.4"
# A point per document: (id, title, lang, its "text" vector).
_DOCS = [
    (1, "Dogs at the beach", "en", [1.0, 0.0, 0.0, 0.0]),
    (2, "Hunde im Park", "de", [0.9, 0.1, 0.0, 0.0]),
    (3, "Cats indoors", "en", [0.0, 1.0, 0.0, 0.0]),
    (4, "Birds in spring", "en", [0.0, 0.0, 1.0, 0.0]),
]
# What the embeddings endpoint answers for a word: the vector nearest the matching documents.
_EMBEDDINGS = {"dogs": [1.0, 0.05, 0.0, 0.0], "cats": [0.0, 1.0, 0.0, 0.0]}


class _Qdrant:
    def __init__(self) -> None:
        from tests.port_lease import lease_ports

        (self.port,) = lease_ports(1)
        self._name = f"provisa-itest-qdrant-{os.getpid()}"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        from qdrant_client import QdrantClient, models

        subprocess.run(
            ["docker", "run", "-d", "--rm", "--memory", "512m", "--name", self._name]
            + ["-p", f"127.0.0.1:{self.port}:6333", _IMAGE],
            check=True,
            capture_output=True,
        )
        deadline = time.monotonic() + 120
        while True:
            try:
                client = QdrantClient(url=self.url)
                client.get_collections()
                break
            except Exception:  # allow-blind-except: polling the container until it answers
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        client.create_collection(
            "docs",
            vectors_config={"text": models.VectorParams(size=4, distance=models.Distance.COSINE)},
        )
        client.create_payload_index("docs", "lang", models.PayloadSchemaType.KEYWORD)
        client.upsert(
            "docs",
            points=[
                models.PointStruct(id=i, vector={"text": v}, payload={"title": t, "lang": lang})
                for i, t, lang, v in _DOCS
            ],
            wait=True,
        )

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self._name], capture_output=True)


class _Embeddings:
    """An OpenAI-compatible ``POST /v1/embeddings`` answering a fixed vector per word."""

    def __init__(self) -> None:
        from tests.port_lease import lease_ports

        (self.port,) = lease_ports(1)

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 -- http.server's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = [{"embedding": _EMBEDDINGS[text]} for text in body["input"]]
                out = json.dumps({"data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                del format, args  # the test's output stays its own

        self._server = HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()


@pytest.fixture(scope="module")
def qdrant():
    q = _Qdrant()
    try:
        q.start()
        yield q
    finally:
        q.stop()


@pytest.fixture(scope="module")
def embeddings():
    e = _Embeddings()
    e.start()
    try:
        yield e
    finally:
        e.stop()


def _col(name: str, data_type: str, **kw) -> dict:
    return {"name": name, "data_type": data_type, "visible_to": [_ROLE], **kw}


def _arg(name: str, data_type: str, *, required: bool = False) -> dict:
    return {
        "name": f"_nf_{name}",
        "data_type": data_type,
        "native_filter_type": "query_arg",
        "native_filter_required": required,
        "visible_to": [],
    }


_RESULT = [
    _col("id", "bigint", path="@id"),
    _col("score", "double", path="@score"),
    _col("title", "varchar"),
    _col("lang", "varchar"),
]


@pytest.fixture(scope="module")
def server(qdrant, embeddings, tmp_path_factory):
    from tests.integration.isolated_server import IsolatedServer

    search = {
        "collection": "docs",
        "query": "@q",
        "using": "text",
        "filter": {"must": [{"key": "lang", "match": {"value": "@lang"}}]},
        "limit": "@k",
    }
    cfg = {
        "federation_engine": "duckdb",
        "auth": {
            "provider": "none",
            "assignments_source": "provisa",
            "default_assignments": [{"domain_id": "*", "role_id": _ROLE}],
        },
        "naming": {"domain_prefix": False, "rules": []},
        "cache": {"enabled": False},
        "vector_models": [
            {"id": "stub", "provider": "openai", "dimensions": 4, "base_url": embeddings.base_url}
        ],
        "domains": [{"id": "kb", "description": "qdrant e2e"}],
        "sources": [{"id": "vec", "type": "qdrant", "host": qdrant.url, "cache_ttl": 60}],
        "tables": [
            {
                "source_id": "vec",
                "domain_id": "kb",
                "schema": "default",
                "table": "docs",
                "cache_ttl": 60,
                "columns": [
                    _col("id", "bigint", path="@id", is_primary_key=True),
                    _col("title", "varchar"),
                    _col("lang", "varchar"),
                ],
            },
            {
                "source_id": "vec",
                "domain_id": "kb",
                "schema": "default",
                "table": "docs_search",
                "cache_ttl": 60,
                "query_template": json.dumps(search),
                "columns": [
                    *_RESULT,
                    _arg("q", "array(double)", required=True),
                    _arg("lang", "varchar"),
                    _arg("k", "integer"),
                ],
            },
            {
                "source_id": "vec",
                "domain_id": "kb",
                "schema": "default",
                "table": "docs_by_text",
                "cache_ttl": 60,
                "query_template": json.dumps(
                    {"collection": "docs", "query": "@q", "using": "text", "model": "stub"}
                ),
                "columns": [*_RESULT, _arg("q", "array(double)", required=True)],
            },
        ],
    }
    work = tmp_path_factory.mktemp("qdrant_e2e")
    path = work / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    srv = IsolatedServer(
        "qdrant_source",
        engine="duckdb",
        config=str(path),
        control_plane="sqlite",
        materialize_store_url=f"duckdb:///{work / 'store.duckdb'}",
    )
    srv.start(timeout=240)
    try:
        yield srv
    finally:
        srv.stop_process()


def _sql(server, sql: str) -> httpx.Response:
    return httpx.post(
        f"{server.base_url}/data/sql",
        json={"sql": sql},
        headers={"X-Provisa-Role": _ROLE},
        timeout=server.request_timeout + 30,
    )


def _rows(resp: httpx.Response) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["sql"]


def test_a_collection_table_is_read_whole(server):
    rows = _rows(_sql(server, "SELECT id, title, lang FROM docs ORDER BY id"))
    assert rows == [{"id": i, "title": t, "lang": lang} for i, t, lang, _ in _DOCS]


def test_a_search_returns_the_nearest_points_nearest_first_with_their_scores(server):
    rows = _rows(
        _sql(
            server,
            "SELECT id, score FROM docs_search WHERE _nf_q = '[1, 0, 0, 0]' AND _nf_k = 2 "
            "ORDER BY score DESC",
        )
    )
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["score"] == pytest.approx(1.0)


def test_the_filter_is_applied_by_qdrant_before_its_nearest_points_are_chosen(server):
    rows = _rows(
        _sql(
            server,
            "SELECT id FROM docs_search WHERE _nf_q = '[1, 0, 0, 0]' AND _nf_lang = 'en' "
            "AND _nf_k = 2 ORDER BY score DESC",
        )
    )
    # Document 2 is the second nearest overall but German: the two nearest English ones answer.
    assert [r["id"] for r in rows] == [1, 3]


def test_a_search_without_its_query_is_refused_naming_it(server):
    resp = _sql(server, "SELECT id FROM docs_search")
    assert resp.status_code != 200
    assert "docs_search" in resp.text and "q" in resp.text


def test_a_text_query_is_embedded_by_the_searchs_model(server):
    rows = _rows(
        _sql(server, "SELECT id FROM docs_by_text WHERE _nf_q = 'cats' ORDER BY score DESC")
    )
    assert rows[0]["id"] == 3


def test_a_search_joins_its_collection(server):
    rows = _rows(
        _sql(
            server,
            "SELECT d.title FROM docs_search s JOIN docs d ON d.id = s.id "
            "WHERE s._nf_q = '[0, 0, 1, 0]' AND s._nf_k = 1",
        )
    )
    assert rows == [{"title": "Birds in spring"}]
