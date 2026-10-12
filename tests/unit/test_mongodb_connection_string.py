# Copyright (c) 2026 Kenneth Stott
# Canary: 1af46115-2e87-45f5-8e15-42d0a4b9eebf
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A MongoDB source reached by a connection string (REQ-1985): every reach of the source uses the
same connection, with the source's credentials kept apart or percent-encoded into the string."""

# Requirements: REQ-1985

from __future__ import annotations

from unittest.mock import patch

import pydantic
import pytest

from provisa.core.models import Source, SourceType
from provisa.federation.clickhouse_connectors import ClickHouseMongoConnector
from provisa.federation.connector_duckdb import DuckDBMongoConnector
from provisa.federation.trino_connectors import TrinoMongoConnector
from provisa.mongodb.fetch import ConnectionStringWithPort, MongoConnection

_SRV = "mongodb+srv://cluster0.abcde.mongodb.net/?retryWrites=true&w=majority"


def _source(host: str, port: int = 0, username: str = "", password: str = "") -> Source:
    return Source(
        id="atlas",
        type=SourceType.mongodb,
        host=host,
        port=port,
        database="sample_mflix",
        username=username,
        password=password,
    )


class _Client:
    def __init__(self, *args, **kwargs) -> None:
        self.args, self.kwargs = args, kwargs

    def close(self) -> None:
        pass


def _opened(source: Source) -> _Client:
    with patch("pymongo.MongoClient", _Client):
        with MongoConnection.from_source(source).client() as client:
            return client


def test_the_native_reader_connects_by_the_connection_string_with_the_credentials_apart():
    client = _opened(_source(_SRV, username="app", password="p@ss:w/rd"))
    assert client.args == (_SRV,)
    assert (client.kwargs["username"], client.kwargs["password"]) == ("app", "p@ss:w/rd")
    # An SRV string forbids directConnection; its own options say how to connect.
    assert "directConnection" not in client.kwargs


def test_a_host_and_port_source_connects_as_before():
    client = _opened(_source("mongo.internal", 27018, "app", "pw"))
    assert client.args == ()
    assert (client.kwargs["host"], client.kwargs["port"]) == ("mongo.internal", 27018)
    assert client.kwargs["directConnection"] is True


def test_a_secret_reference_resolves_to_the_connection_string_at_use(monkeypatch):
    monkeypatch.setenv("ATLAS_URI", _SRV)
    monkeypatch.setenv("ATLAS_PASSWORD", "s3cret")
    client = _opened(_source("${env:ATLAS_URI}", username="app", password="${env:ATLAS_PASSWORD}"))
    assert client.args == (_SRV,)
    assert client.kwargs["password"] == "s3cret"


def test_the_credentials_are_percent_encoded_into_a_connection_string():
    conn = MongoConnection.from_source(_source(_SRV, username="app user", password="p@ss:w/rd"))
    assert conn.url() == (
        "mongodb+srv://app%20user:p%40ss%3Aw%2Frd@cluster0.abcde.mongodb.net/"
        "?retryWrites=true&w=majority"
    )
    plain = MongoConnection.from_source(_source("mongo.internal", 27018, "app", "p@ss"))
    assert plain.url() == "mongodb://app:p%40ss@mongo.internal:27018/"


def test_a_connection_string_naming_its_own_user_is_used_as_given():
    given = "mongodb://reader:pw@h1:27017,h2:27017/?replicaSet=rs0&tls=true"
    assert MongoConnection.from_source(_source(given)).url() == given


def test_the_trino_and_duckdb_attaches_use_the_connection_string():
    source = _source(_SRV, username="app", password="p@ss")
    url = "mongodb+srv://app:p%40ss@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority"
    assert TrinoMongoConnector().details(source)["mongodb.connection-url"] == url
    assert DuckDBMongoConnector().details(source)["attach"] == (
        f"ATTACH '{url}' AS \"_src_atlas\" (TYPE mongo)"
    )


def test_the_clickhouse_engine_refuses_a_source_given_by_a_connection_string():
    with pytest.raises(ValueError, match="'atlas'.*one host and port"):
        ClickHouseMongoConnector().details(_source(_SRV))


def test_a_connection_string_with_a_port_is_refused_naming_the_source():
    with pytest.raises(pydantic.ValidationError, match="'atlas'.*leave the port empty"):
        _source(_SRV, port=27017)


def test_a_secret_reference_resolving_to_a_connection_string_with_a_port_is_refused_at_use(
    monkeypatch,
):
    monkeypatch.setenv("ATLAS_URI", _SRV)
    with pytest.raises(ConnectionStringWithPort, match="'atlas'"):
        MongoConnection.from_source(_source("${env:ATLAS_URI}", port=27017))
