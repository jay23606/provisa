# Copyright (c) 2026 Kenneth Stott
# Canary: 62d558aa-1af5-482b-9ca6-febf57f02888
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1997: every kind of location a file-based source reads -- a file on this node, https,
s3, gs and az -- one test per family: what DuckDB is given to reach it (its extension and the
store's secret, scoped to the bucket), a SQLite or DuckDB file elsewhere attached read-only and
offering no writes, and a remote SQLite file read on an engine that does not attach it."""

from __future__ import annotations

import functools
import http.server
import sqlite3
import threading
from types import SimpleNamespace

import duckdb
import pytest

from provisa.executor.write_capability import table_write_ops
from provisa.federation.connector_duckdb import (
    DuckDBCsvConnector,
    DuckDBDuckdbConnector,
    DuckDBParquetConnector,
    DuckDBSqliteConnector,
    location_kind,
)

CONNECTORS = {
    "csv": DuckDBCsvConnector(),
    "parquet": DuckDBParquetConnector(),
    "sqlite": DuckDBSqliteConnector(),
    "duckdb": DuckDBDuckdbConnector(),
}
S3 = {"access_key_id": "AKIA", "secret_access_key": "s'cret", "region": "eu-west-1"}
GCS = {"gcs_access_id": "GOOG1", "gcs_secret_key": "hmac"}
AZURE = {"azure_account_name": "acct", "azure_account_key": "key=="}


def _source(type_: str, path: str, hints: dict | None = None):
    return SimpleNamespace(id="files-1", type=type_, path=path, federation_hints=hints or {})


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/data/a.csv", None),
        ("file:///data/a.csv", None),
        ("https://example.com/a.csv", "http"),
        ("s3://bucket/a.csv", "s3"),
        ("gs://bucket/a.csv", "gcs"),
        ("az://container/a.csv", "azure"),
        ("abfss://container@acct.dfs.core.windows.net/a.csv", "azure"),
    ],
)
def test_where_a_path_is(path, kind):
    assert location_kind(path) == kind


def test_a_scheme_duckdb_does_not_read_is_refused_by_name():
    with pytest.raises(ValueError, match="ftp://"):
        location_kind("ftp://host/a.csv")


# --- one family at a time ------------------------------------------------------------------


@pytest.mark.parametrize("type_", list(CONNECTORS))
def test_a_file_on_this_node_needs_nothing_and_only_a_duckdb_file_is_read_only(type_):
    details = CONNECTORS[type_].details(_source(type_, "/data/f"))
    assert "secret_ddl" not in details and "extensions" not in details
    if type_ == "sqlite":
        assert details["attach"].endswith("(TYPE sqlite)")
    if type_ == "duckdb":
        assert details["attach"].endswith("(TYPE duckdb, READ_ONLY)")


@pytest.mark.parametrize("type_", list(CONNECTORS))
def test_https_is_reached_through_httpfs_with_no_secret_and_attached_read_only(type_):
    details = CONNECTORS[type_].details(_source(type_, "https://example.com/f"))
    assert details["extensions"] == ["httpfs"] and "secret_ddl" not in details
    if "attach" in details:
        assert "READ_ONLY" in details["attach"]


@pytest.mark.parametrize("type_", list(CONNECTORS))
def test_s3_takes_its_key_scoped_to_its_bucket(type_):
    details = CONNECTORS[type_].details(_source(type_, "s3://bucket/dir/f", S3))
    assert details["extensions"] == ["httpfs"]
    secret = details["secret_ddl"]
    assert "TYPE s3" in secret and "KEY_ID 'AKIA'" in secret and "SECRET 's''cret'" in secret
    assert "REGION 'eu-west-1'" in secret and "SCOPE 's3://bucket'" in secret
    if "attach" in details:
        assert "READ_ONLY" in details["attach"]


@pytest.mark.parametrize("type_", list(CONNECTORS))
def test_gcs_takes_its_hmac_key_scoped_to_its_bucket(type_):
    details = CONNECTORS[type_].details(_source(type_, "gs://bucket/f", GCS))
    assert details["extensions"] == ["httpfs"]
    assert details["secret_ddl"] == (
        "CREATE OR REPLACE SECRET \"_os_files-1\" (TYPE gcs, KEY_ID 'GOOG1', SECRET 'hmac', "
        "SCOPE 'gs://bucket')"
    )


@pytest.mark.parametrize("type_", list(CONNECTORS))
def test_azure_takes_its_account_key_through_the_azure_extension(type_):
    details = CONNECTORS[type_].details(_source(type_, "az://container/f", AZURE))
    assert details["extensions"] == ["azure"]
    secret = details["secret_ddl"]
    assert "TYPE azure" in secret and "AccountName=acct;AccountKey=key==" in secret
    assert "SCOPE 'az://container'" in secret


def test_a_public_object_store_location_gets_no_secret():
    assert "secret_ddl" not in DuckDBParquetConnector().details(_source("parquet", "s3://open/f"))


# --- writes -----------------------------------------------------------------------------------


@pytest.mark.parametrize("type_", ["sqlite", "duckdb"])
@pytest.mark.parametrize("path", ["https://example.com/f", "s3://b/f", "gs://b/f", "az://c/f"])
def test_a_file_database_elsewhere_offers_no_writes(type_, path):
    assert table_write_ops({"table_name": "t"}, type_, None, source_path=path) == frozenset()


@pytest.mark.parametrize("type_", ["sqlite", "duckdb"])
def test_a_file_database_on_this_node_offers_its_writes(type_):
    offered = table_write_ops({"table_name": "t"}, type_, None, source_path="/data/f")
    assert offered == {"insert", "update", "delete"}


# --- read for real over http ---------------------------------------------------------------


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 -- the base class's own signature
        return


@pytest.fixture
def served(tmp_path):
    """A directory served over http on this host, in this process."""
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=str(tmp_path))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield tmp_path, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _sqlite_file(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE orders (id INTEGER, region TEXT)")
    con.execute("INSERT INTO orders VALUES (1, 'east'), (2, 'west')")
    con.commit()
    con.close()


def test_duckdb_reads_a_sqlite_and_a_duckdb_file_over_http_read_only(served):
    root, base = served
    _sqlite_file(root / "s.sqlite")
    made = duckdb.connect(str(root / "d.duckdb"))
    made.execute("CREATE TABLE orders AS SELECT 3 AS id, 'north' AS region")
    made.close()
    con = duckdb.connect()
    con.execute("INSTALL sqlite; LOAD sqlite; INSTALL httpfs; LOAD httpfs")
    for type_, name in (("sqlite", "s.sqlite"), ("duckdb", "d.duckdb")):
        details = CONNECTORS[type_].details(_source(type_, f"{base}/{name}"))
        con.execute(details["attach"])
        alias = details["raw_alias"]
        assert con.execute(f'SELECT count(*) FROM "{alias}".main.orders').fetchone()[0] >= 1
        with pytest.raises(duckdb.Error, match="read-only"):
            con.execute(f"INSERT INTO \"{alias}\".main.orders VALUES (9, 'x')")
        con.execute(f'DETACH "{alias}"')


async def test_a_remote_sqlite_file_is_landed_on_an_engine_that_does_not_attach_it(served):
    from provisa.events.source_loader import make_sqlite_loader

    root, base = served
    _sqlite_file(root / "s.sqlite")
    loader = make_sqlite_loader()
    source = _source("sqlite", f"{base}/s.sqlite")
    table = SimpleNamespace(
        table_name="orders",
        columns=[
            SimpleNamespace(name="id", native_filter_type=None),
            SimpleNamespace(name="region", native_filter_type=None),
        ],
    )
    rows = await loader(source, table)
    assert sorted((r["id"], r["region"]) for r in rows) == [(1, "east"), (2, "west")]
    replica = loader.replica_source(source, table, [("id", "bigint"), ("region", "text")])
    batches = [b async for b in replica.batches(1)]
    assert sum(b.num_rows for b in batches) == 2
