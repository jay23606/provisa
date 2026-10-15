# Copyright (c) 2026 Kenneth Stott
# Canary: 9c3f7a41-5b28-4d6e-8f10-6a2d94b3ce77
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""True E2E for Cassandra as a connector-source: registration through to a served query.

``test_cassandra_source_e2e.py`` proves Trino can reach Cassandra. This proves Provisa can, which
is a strictly larger claim — see ``connector_source_harness`` for why the gap between the two is
where a connector source actually fails (introspection-driven registration, and agreement between
the recorded catalog name and the physically created one).

Cassandra is the pathfinder for the connector-only family because it boots fastest and its Trino
connector is a first-party one with a conventional ``information_schema``; if the harness cannot
drive this source, the harness is wrong rather than the source.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from tests.integration.connector_source_harness import (
    assert_registration_and_query,
    connector_client,  # noqa: F401 — imported for pytest fixture discovery
    query_semantic,
)
from tests.itest_stack import ITEST_PROJECT as _ITEST_PROJECT

pytestmark = [
    pytest.mark.requires_trino,
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="session"),
]

_KEYSPACE = "provisa_pipeline"
_TABLE = "widgets"
_WIDGETS = [(1, "Widget A"), (2, "Widget B"), (3, "Widget C")]

# The source id doubles as the catalog name (``source_to_catalog`` only maps ``-`` → ``_``), and
# ``database`` is left empty so ``createSource``'s recorded catalog and ``create_catalog``'s
# physical one cannot diverge. Keeping them in agreement is the point of the assertion, not an
# incidental choice — see the harness docstring on schema_mutation.py:378-381.
_SOURCE_ID = "cassandra_pipeline"
_DOMAIN = "cass_e2e"


def _cassandra_container_id() -> str:
    out = subprocess.run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={_ITEST_PROJECT}",
            "--filter",
            "label=com.docker.compose.service=cassandra",
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    ids = out.splitlines()
    if not ids:
        raise RuntimeError(f"No running cassandra container for project {_ITEST_PROJECT!r}")
    return ids[0]


def _cqlsh(container_id: str, statement: str) -> None:
    subprocess.run(
        ["docker", "exec", container_id, "cqlsh", "-e", statement],
        capture_output=True,
        text=True,
        check=True,
    )


def _seed_cassandra() -> None:
    """Create the keyspace/table and insert 3 rows, retrying while schema agreement settles."""
    container_id = _cassandra_container_id()
    ddl = (
        f"CREATE KEYSPACE IF NOT EXISTS {_KEYSPACE} "
        "WITH replication = {'class':'SimpleStrategy','replication_factor':1}"
    )
    deadline = time.monotonic() + 60
    last_err: subprocess.CalledProcessError | None = None
    while time.monotonic() < deadline:
        try:
            _cqlsh(container_id, ddl)
            break
        except subprocess.CalledProcessError as e:
            last_err = e
            time.sleep(3)
    else:
        raise RuntimeError(f"cassandra keyspace creation never succeeded: {last_err!r}")

    _cqlsh(
        container_id,
        f"CREATE TABLE IF NOT EXISTS {_KEYSPACE}.{_TABLE} (id int PRIMARY KEY, name text)",
    )
    for wid, name in _WIDGETS:
        _cqlsh(
            container_id, f"INSERT INTO {_KEYSPACE}.{_TABLE} (id, name) VALUES ({wid}, '{name}')"
        )


@pytest.mark.requires_cassandra
async def test_cassandra_registers_and_serves_semantic_query(connector_client):  # noqa: F811
    """createSource → registerTable (types introspected) → rebuildSchemas → semantic SELECT.

    ``host="cassandra"`` is the compose service name: Trino dials it on the isolated stack's
    private network. The test process never opens a Cassandra connection itself — seeding goes
    through ``cqlsh`` inside the container — so nothing here depends on a host-published port.
    """
    _seed_cassandra()

    await assert_registration_and_query(
        connector_client,
        source_id=_SOURCE_ID,
        source_type="cassandra",
        host="cassandra",
        port=9042,
        domain_id=_DOMAIN,
        schema_name=_KEYSPACE,
        table_name=_TABLE,
        columns=["id", "name"],
        order_by="id",
        expected_rows=[{"id": i, "name": n} for i, n in _WIDGETS],
    )


_WRITE_SOURCE_ID = "cassandra_writes"
_WRITE_DOMAIN = "cass_writes"
_WRITE_TABLE = "gadgets"


def _cql_rows(container_id: str, statement: str) -> list[str]:
    """The data lines cqlsh prints for ``statement`` (header, rule and row count dropped)."""
    out = subprocess.run(
        ["docker", "exec", container_id, "cqlsh", "-e", statement],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return [ln for ln in lines[2:] if not ln.startswith("(")]


@pytest.mark.requires_cassandra
async def test_cassandra_takes_an_insert_through_provisa(connector_client):  # noqa: F811
    """An INSERT through Provisa's one write path lands in Cassandra (the Trino connector's
    write), and an UPDATE — which Cassandra through Trino cannot carry — is refused by name.

    The table is registered writable by the role; the write goes through ``/data/sql`` — the
    governed pipeline, the write admission, the engine route — and is read back both from
    Cassandra itself (``cqlsh``) and through Provisa.
    """
    container_id = _cassandra_container_id()
    _seed_cassandra()  # the keyspace
    _cqlsh(
        container_id,
        f"CREATE TABLE IF NOT EXISTS {_KEYSPACE}.{_WRITE_TABLE} (id int PRIMARY KEY, name text)",
    )
    _cqlsh(container_id, f"TRUNCATE {_KEYSPACE}.{_WRITE_TABLE}")
    _cqlsh(
        container_id, f"INSERT INTO {_KEYSPACE}.{_WRITE_TABLE} (id, name) VALUES (1, 'Gadget A')"
    )

    await assert_registration_and_query(
        connector_client,
        source_id=_WRITE_SOURCE_ID,
        source_type="cassandra",
        host="cassandra",
        port=9042,
        domain_id=_WRITE_DOMAIN,
        schema_name=_KEYSPACE,
        table_name=_WRITE_TABLE,
        columns=["id", "name"],
        order_by="id",
        expected_rows=[{"id": 1, "name": "Gadget A"}],
        writable_by=["org_admin"],
    )

    target = f'"{_WRITE_DOMAIN}"."{_WRITE_TABLE}"'
    written = await connector_client.post(
        "/data/sql",
        json={
            "sql": f"INSERT INTO {target} (id, name) VALUES (2, 'Gadget B')",
            "role": "org_admin",
        },
    )
    assert written.status_code == 200, written.text

    # In Cassandra itself, not only as Provisa reports it.
    landed = _cql_rows(
        container_id, f"SELECT id, name FROM {_KEYSPACE}.{_WRITE_TABLE} WHERE id = 2"
    )
    assert len(landed) == 1 and "Gadget B" in landed[0], landed
    served = await query_semantic(
        connector_client, f'SELECT "id", "name" FROM {target} ORDER BY "id"'
    )
    assert served == [{"id": 1, "name": "Gadget A"}, {"id": 2, "name": "Gadget B"}]

    # Cassandra through Trino takes inserts only: an UPDATE is refused before anything runs.
    refused = await connector_client.post(
        "/data/sql",
        json={"sql": f"UPDATE {target} SET name = 'changed' WHERE id = 1", "role": "org_admin"},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "data.write_not_supported", refused.text
    assert refused.json()["params"] == {"table": _WRITE_TABLE, "operation": "UPDATE"}
    unchanged = _cql_rows(container_id, f"SELECT name FROM {_KEYSPACE}.{_WRITE_TABLE} WHERE id = 1")
    assert unchanged == ["Gadget A"], unchanged
