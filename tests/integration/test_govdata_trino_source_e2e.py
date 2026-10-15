# Copyright (c) 2026 Kenneth Stott
# Canary: 1808a691-74db-40fc-ad5d-06d7cea8acd7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""AskAmerica on Trino, LIVE, through Trino's built-in PostgreSQL connector (REQ-540).

This is the test ``trino_connectors.TRINO_READS_PGWIRE_ADAPTER_LIVE`` waits for. It points a
``postgresql`` catalog at the source's bundled ``pgwire-govdata`` server -- the endpoint DuckDB,
Postgres and ClickHouse attach -- and settles what reading the adapter's source cannot:

- that the PostgreSQL JDBC driver's metadata queries (getSchemas / getTables / getColumns) parse
  on the adapter's pg_catalog emulation and return the source's schemas, tables and columns;
- that rows come back over the extended protocol in the formats the driver asks for;
- how Trino's lower-cased names resolve against the adapter (``case-insensitive-name-matching``);
- that a table reads alone and joined with a table of another catalog in one statement.

Each step runs in order and names the statement it failed on; the adapter's own log is
attached to the failure, since the adapter is where the cause will be.

Reachability
------------
Trino runs in a container here and the adapter on the test host, so the lane sets
``PROVISA_PGWIRE_BIND_HOST`` (the address the adapter listens on: the container bridge's) and
``PROVISA_PGWIRE_ENGINE_HOST`` (the name Trino reaches it by). Both are required: without them
the adapter listens on loopback, which the container cannot reach, and the test says so.

Credentials: ``ASKAMERICA_API_KEY`` (a secret of the warehouse lane).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest

from tests.conftest import as_deployment_org

pytestmark = [pytest.mark.integration, pytest.mark.requires_warehouse]

_SOURCE_ID = "askamerica-trino-itest"
_CATALOG = "askamerica_trino_itest"
_SCHEMAS = "fec,ref,geo"
_SCHEMA = "fec"
_TABLE = "candidates"
_COLD_START_SECONDS = 600
_TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
_TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))


def _required(name: str, why: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set: {why}")
    return value


def _source():
    from provisa.core.models import Source, SourceType

    return Source(
        id=_SOURCE_ID,
        type=SourceType.govdata,
        username=_required("ASKAMERICA_API_KEY", "the AskAmerica source needs a real key"),
        database=_SCHEMAS,
    )


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """The source's server, bound where the Trino container reaches it; yields its state dir."""
    from provisa.federation import pgwire_replica as pr

    _required(pr.BIND_HOST_ENV, "the adapter must listen where the Trino container reaches it")
    _required(pr.ENGINE_HOST_ENV, "Trino needs the name it reaches the adapter's host by")
    data_dir = tmp_path_factory.mktemp("askamerica-trino-state")
    previous = os.environ.get("PROVISA_DATA_DIR")
    os.environ["PROVISA_DATA_DIR"] = str(data_dir)
    source = _source()
    try:
        with as_deployment_org():
            pr.ensure_endpoint(source, timeout=_COLD_START_SECONDS)
        yield source, data_dir
    finally:
        with as_deployment_org():
            pr.stop_endpoint(source.id)
        if previous is None:
            del os.environ["PROVISA_DATA_DIR"]
        else:
            os.environ["PROVISA_DATA_DIR"] = previous


def _adapter_log(data_dir: Path) -> str:
    logs = sorted(Path(data_dir).rglob("pgwire-server.log"))
    if not logs:
        return "(the adapter wrote no log)"
    return "\n".join(logs[-1].read_text(errors="replace").splitlines()[-80:])


@contextlib.contextmanager
def _step(what: str, sql: str, data_dir: Path):
    """Name the statement a failure happened on and attach the end of the adapter's log."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - re-raised with the statement and the adapter's log
        raise AssertionError(
            f"{what} failed on:\n  {sql}\n{type(exc).__name__}: {exc}\n"
            f"--- adapter log (end) ---\n{_adapter_log(data_dir)}"
        ) from exc


@pytest.fixture(scope="module")
def catalog(served):
    """A Trino ``postgresql`` catalog over the adapter, built from the product's own connector."""
    import trino.dbapi

    from provisa.federation.trino_connectors import TrinoGovdataConnector

    source, data_dir = served
    props = TrinoGovdataConnector().details(source)
    with_clause = ", ".join(f"\"{k}\" = '{v}'" for k, v in props.items())
    create = f"CREATE CATALOG {_CATALOG} USING postgresql WITH ({with_clause})"
    conn = trino.dbapi.connect(host=_TRINO_HOST, port=_TRINO_PORT, user="provisa")
    cur = conn.cursor()
    cur.execute(f"DROP CATALOG IF EXISTS {_CATALOG}")
    cur.fetchall()
    with _step("creating the catalog", create, data_dir):
        cur.execute(create)
        cur.fetchall()
    try:
        yield cur, data_dir
    finally:
        cur.execute(f"DROP CATALOG IF EXISTS {_CATALOG}")
        cur.fetchall()
        conn.close()


def _run(cur, what: str, sql: str, data_dir: Path) -> list:
    with _step(what, sql, data_dir):
        cur.execute(sql)
        return cur.fetchall()


def test_trino_reads_an_askamerica_table_live_and_joins_it(catalog):
    cur, data_dir = catalog

    schemas = {
        r[0] for r in _run(cur, "listing schemas", f"SHOW SCHEMAS FROM {_CATALOG}", data_dir)
    }
    assert _SCHEMA in schemas, schemas
    assert schemas - {"information_schema", "pg_catalog"} <= set(_SCHEMAS.split(",")), schemas

    tables = {
        r[0]
        for r in _run(cur, "listing tables", f"SHOW TABLES FROM {_CATALOG}.{_SCHEMA}", data_dir)
    }
    assert _TABLE in tables, tables

    columns = _run(cur, "describing the table", f"DESCRIBE {_CATALOG}.{_SCHEMA}.{_TABLE}", data_dir)
    assert columns, "the table has no columns Trino could map"

    rows = _run(
        cur,
        "reading the table alone",
        f"SELECT * FROM {_CATALOG}.{_SCHEMA}.{_TABLE} LIMIT 5",
        data_dir,
    )
    assert len(rows) == 5

    first = columns[0][0]
    filtered = _run(
        cur,
        "a pushed-down predicate",
        f'SELECT count(*) FROM {_CATALOG}.{_SCHEMA}.{_TABLE} WHERE "{first}" IS NOT NULL',
        data_dir,
    )
    assert filtered[0][0] >= 0

    joined = _run(
        cur,
        "joining with a table of another catalog",
        f"SELECT count(*) FROM (SELECT * FROM {_CATALOG}.{_SCHEMA}.{_TABLE} LIMIT 5) c "
        "CROSS JOIN (SELECT node_id FROM system.runtime.nodes LIMIT 1) n",
        data_dir,
    )
    assert joined[0][0] == 5
