# Copyright (c) 2026 Kenneth Stott
# Canary: c2ca48e8-b8b4-496d-aa66-7d40b3a48477
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Spike (REQ-1982, maintainer decision 5): does the Cosmos DB Linux emulator serve vector search
and full-text search? Each feature is one test, so the CI result answers per feature. Where a
feature fails here, the Cosmos search tests it would back need a real Cosmos account, and the
maintainer decides whether CI gets one.

The emulator is the ``test`` instance: a container this module starts on a leased port and
removes. It speaks HTTP and takes the emulator's well-known key."""

# Requirements: REQ-1982

from __future__ import annotations

import os
import subprocess
import time

import pytest

pytestmark = [pytest.mark.integration]

_IMAGE = "mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview"
# The emulator's published, well-known account key (not a secret).
_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
_DOCS = [
    {
        "id": "1",
        "pk": "a",
        "text": "an old man flies his house with balloons",
        "embedding": [1.0, 0.0, 0.0],
    },
    {
        "id": "2",
        "pk": "a",
        "text": "a race car learns about friendship",
        "embedding": [0.9, 0.1, 0.0],
    },
    {"id": "3", "pk": "b", "text": "a detective chases bank robbers", "embedding": [0.0, 1.0, 0.0]},
]


@pytest.fixture(scope="module")
def container():
    from azure.cosmos import CosmosClient, PartitionKey

    from tests.port_lease import lease_ports

    (port,) = lease_ports(1)
    name = f"provisa-itest-cosmos-{os.getpid()}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--memory", "2g", "--name", name]
        + ["-p", f"127.0.0.1:{port}:8081", _IMAGE],
        check=True,
        capture_output=True,
    )
    try:
        # The client's constructor already asks the account for its endpoints, so it is made inside
        # the wait: until the emulator listens, the port's proxy resets the connection.
        deadline = time.monotonic() + 300
        while True:
            try:
                client = CosmosClient(f"http://127.0.0.1:{port}/", credential=_KEY)
                db = client.create_database_if_not_exists("spike")
                break
            except Exception:  # allow-blind-except: polling the emulator until it answers
                if time.monotonic() > deadline:
                    raise
                time.sleep(3)
        made = db.create_container(
            id="docs",
            partition_key=PartitionKey(path="/pk"),
            vector_embedding_policy={
                "vectorEmbeddings": [
                    {
                        "path": "/embedding",
                        "dataType": "float32",
                        "distanceFunction": "cosine",
                        "dimensions": 3,
                    }
                ]
            },
            full_text_policy={
                "defaultLanguage": "en-US",
                "fullTextPaths": [{"path": "/text", "language": "en-US"}],
            },
            indexing_policy={
                "indexingMode": "consistent",
                "includedPaths": [{"path": "/*"}],
                "excludedPaths": [{"path": '/"_etag"/?'}, {"path": "/embedding/*"}],
                "vectorIndexes": [{"path": "/embedding", "type": "flat"}],
                "fullTextIndexes": [{"path": "/text"}],
            },
        )
        for doc in _DOCS:
            made.upsert_item(doc)
        yield made
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _query(container, sql: str, parameters: list[dict] | None = None) -> list[dict]:
    return list(
        container.query_items(sql, parameters=parameters or [], enable_cross_partition_query=True)
    )


def test_the_emulator_serves_a_parameterized_query(container):
    rows = _query(container, "SELECT c.id FROM c WHERE c.pk = @pk", [{"name": "@pk", "value": "a"}])
    assert sorted(r["id"] for r in rows) == ["1", "2"]


def test_the_emulator_serves_vector_search(container):
    rows = _query(
        container,
        "SELECT TOP 2 c.id, VectorDistance(c.embedding, @v) AS score FROM c "
        "ORDER BY VectorDistance(c.embedding, @v)",
        [{"name": "@v", "value": [1.0, 0.0, 0.0]}],
    )
    assert [r["id"] for r in rows] == ["1", "2"]


def test_the_emulator_serves_full_text_contains(container):
    rows = _query(container, "SELECT c.id FROM c WHERE FullTextContains(c.text, 'car')")
    assert [r["id"] for r in rows] == ["2"]


def test_the_emulator_serves_full_text_ranking(container):
    rows = _query(
        container, "SELECT TOP 2 c.id FROM c ORDER BY RANK FullTextScore(c.text, ['old', 'man'])"
    )
    assert rows[0]["id"] == "1"


def test_the_emulator_serves_hybrid_ranking(container):
    rows = _query(
        container,
        "SELECT TOP 2 c.id FROM c ORDER BY RANK RRF(FullTextScore(c.text, ['car']), "
        "VectorDistance(c.embedding, @v))",
        [{"name": "@v", "value": [0.9, 0.1, 0.0]}],
    )
    assert rows[0]["id"] == "2"
