# Copyright (c) 2026 Kenneth Stott
# Canary: b4e9f2a6-7c1d-4e83-9a5f-6d2b8c4e91f7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""MongoDB over the wire protocol, engine-independently (REQ-1730).

Trino's own connector (``TrinoMongoConnector``) was the only reader of a MongoDB source — every
self-only warehouse engine (Snowflake, BigQuery, Databricks, mssql/Fabric/Synapse) and DuckDB itself
has no live MongoDB reach at all, the same gap REQ-1672/1675/1676 already closed for
Elasticsearch/Redis/Cassandra. This module is the native reader (``pymongo``): a database is the
schema, a collection is the table. Synchronous — callers run it in a thread.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

_DEFAULT_PORT = 27017
# REQ-1985: a source's host may be a connection string instead of a host name.
_URI_SCHEMES = ("mongodb://", "mongodb+srv://")


def is_connection_string(host: str) -> bool:
    """Whether ``host`` is a MongoDB connection string rather than a host name (REQ-1985)."""
    return host.startswith(_URI_SCHEMES)


class ConnectionStringWithPort(ValueError):
    """A MongoDB source given both a connection string and a port (REQ-1985): the string carries
    its hosts, so a port beside it would be ignored or contradict it."""

    code = "schema.mongodb_connection_string_with_port"

    def __init__(self, source_id: str) -> None:
        self.params = {"source": source_id}
        super().__init__(
            f"source {source_id!r}: the host is a connection string, which carries its hosts and "
            "ports; leave the port empty"
        )


@dataclass(frozen=True)
class MongoConnection:  # REQ-1730, REQ-1985
    """How a MongoDB source is reached: a host and port, or a connection string (``uri``) that
    carries the hosts and the connection options (tls among them). The credentials are held
    apart from either, already resolved."""

    host: str
    port: int = _DEFAULT_PORT
    username: str | None = None
    password: str | None = None
    uri: str | None = None

    @classmethod
    def build(
        cls, host: str, port: int, *, username: str | None = None, password: str | None = None
    ) -> "MongoConnection":
        return cls(
            host=host or "localhost",
            port=port or _DEFAULT_PORT,
            username=username or None,
            password=password if (username and password) else None,
        )

    @classmethod
    def from_source(cls, source: Any) -> "MongoConnection":
        """The source's connection, its host, username and password resolved here, at use. A host
        that is a connection string is used as given, with no port (REQ-1985)."""
        from provisa.core.secrets import resolve_secrets

        host = resolve_secrets(getattr(source, "host", "") or "")
        username = resolve_secrets(getattr(source, "username", "") or "") or None
        password = resolve_secrets(getattr(source, "password", "") or "") or None
        port = int(getattr(source, "port", 0) or 0)
        if is_connection_string(host):
            if port:
                raise ConnectionStringWithPort(source.id)
            return cls(
                host="",
                port=0,
                username=username,
                password=password if username else None,
                uri=host,
            )
        return cls.build(host, port, username=username, password=password)

    def url(self) -> str:
        """The connection as one connection string, the credentials percent-encoded into it, for a
        reach that takes only a string (the Trino and DuckDB attaches). A connection string that
        already names a user is used as given."""
        from urllib.parse import quote

        user = ""
        if self.username:
            user = quote(self.username, safe="")
            if self.password:
                user += ":" + quote(self.password, safe="")
            user += "@"
        if self.uri is None:
            return f"mongodb://{user}{self.host}:{self.port}/"
        scheme, _, rest = self.uri.partition("://")
        if "@" in rest.split("/", 1)[0]:
            return self.uri
        return f"{scheme}://{user}{rest}"

    def _client(self, timeout_ms: int) -> Any:
        from pymongo import MongoClient

        if self.uri is not None:
            # The connection string carries its own topology options (directConnection,
            # replicaSet, tls); an SRV string forbids directConnection.
            return MongoClient(
                self.uri,
                username=self.username,
                password=self.password,
                serverSelectionTimeoutMS=timeout_ms,
            )
        # directConnection=True: without it, pymongo's replica-set discovery (SDAM) trusts the
        # server's own hello/isMaster response for where to actually connect -- a single-node
        # replica set started for transaction/change-stream support (mongo:7 --replSet, the
        # perf-bench compose posture) self-reports its Docker-internal hostname (e.g.
        # "mongodb:27017") as that address, which is unresolvable from outside the compose
        # network. Confirmed live: every real query against provisa-perf-bench's order_docs
        # (row_materialize keyed fetch, REQ-1865) hung ~150-210s and failed with an EMPTY
        # exception message -- pymongo silently redirected to "mongodb:27017", retried against
        # it until serverSelectionTimeoutMS elapsed, and the caller's own outer
        # concurrent.futures.TimeoutError (str() == "") surfaced first. directConnection=True
        # makes the driver honor host/port as given and skip topology discovery entirely.
        return MongoClient(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            serverSelectionTimeoutMS=timeout_ms,
            directConnection=True,
        )

    @contextmanager
    def client(self) -> Iterator[Any]:
        client = self._client(30000)
        try:
            yield client
        finally:
            client.close()


def _coerce(value: Any) -> Any:
    """A document field value, JSON/Arrow-safe: BSON's ``ObjectId``/``datetime`` pass through
    everywhere else in the pipeline as opaque objects otherwise (the same reason ``fetch_rows``'s
    every sibling module — cassandra/redis/elasticsearch — never returns a driver-native type)."""
    from bson import ObjectId

    if isinstance(value, ObjectId):
        return str(value)
    return value


def fetch_rows(
    conn: MongoConnection, database: str, collection: str, columns: list[str]
) -> list[dict]:  # REQ-1730
    """Every document of ``database.collection``, ``columns`` projected (``_id`` excluded unless
    named), read via a single find-all cursor."""
    return [
        row
        for batch in iter_row_batches(conn, database, collection, columns, _CURSOR_BATCH_ROWS)
        for row in batch
    ]


_CURSOR_BATCH_ROWS = 1000


def iter_row_batches(
    conn: MongoConnection, database: str, collection: str, columns: list[str], batch_rows: int
) -> Iterator[list[dict]]:  # REQ-1915
    """The documents of ``database.collection`` in batches of at most ``batch_rows`` rows, off
    one find-all cursor that fetches that many per round trip: only one batch is held."""
    projection = {c: 1 for c in columns}
    if "_id" not in columns:
        projection["_id"] = 0
    with conn.client() as client:
        cursor = client[database][collection].find({}, projection).batch_size(batch_rows)
        batch: list[dict] = []
        for doc in cursor:
            batch.append({c: _coerce(doc.get(c)) for c in columns})
            if len(batch) >= batch_rows:
                yield batch
                batch = []
        if batch:
            yield batch


def fetch_rows_by_keys(
    conn: MongoConnection,
    database: str,
    collection: str,
    columns: list[str],
    pk_columns: list[str],
    keys: list[tuple[Any, ...]],
) -> list[dict]:  # REQ-1865
    """Exactly the documents whose ``pk_columns`` match one of ``keys`` (REQ-1865 keyed fetch) —
    a bound ``$in``/``$or`` filter, never a full-collection scan. Single-column key: ``$in``;
    composite key: ``$or`` of per-key ``$and`` equality filters (Mongo has no native tuple-IN)."""
    if not keys:
        return []
    projection = {c: 1 for c in columns}
    if "_id" not in columns:
        projection["_id"] = 0
    if len(pk_columns) == 1:
        query = {pk_columns[0]: {"$in": [k[0] for k in keys]}}
    else:
        query = {"$or": [{c: v for c, v in zip(pk_columns, key)} for key in keys]}
    rows: list[dict] = []
    with conn.client() as client:
        for doc in client[database][collection].find(query, projection):
            rows.append({c: _coerce(doc.get(c)) for c in columns})
    return rows


class ChangeStreamsUnavailable(ValueError):
    """A MongoDB table's change feed was asked for (change signal ``native``) on a server that
    serves no change streams: a standalone mongod. Change streams need a replica set (or a
    sharded cluster through mongos); the alternative is a polled refresh (REQ-1861)."""

    code = "schema.change_streams_unavailable"

    def __init__(self, source_id: str) -> None:
        self.params = {"source": source_id}
        super().__init__(
            f"source {source_id!r} is a standalone MongoDB server, which serves no change "
            "streams: the native change signal needs a replica set or a sharded cluster. Run "
            "it as a replica set, or use the poll change signal."
        )


def require_change_streams(conn: MongoConnection, source_id: str) -> None:  # REQ-1861
    """Refuse a server that serves no change streams (:class:`ChangeStreamsUnavailable`). The
    server's ``hello`` says what it is: a replica set member names its set, a mongos says it is
    one. A server that cannot be reached raises the driver's own error -- never a pass."""
    client = conn._client(5000)
    try:
        hello = client.admin.command("hello")
    finally:
        client.close()
    if not (hello.get("setName") or hello.get("msg") == "isdbgrid"):
        raise ChangeStreamsUnavailable(source_id)
