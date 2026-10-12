# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1867: resolving a Databricks Unity Catalog table's live Iceberg metadata and the storage
credentials it vends, through Unity Catalog's Iceberg REST catalog (iceberg-rest/v1; #243).

The HTTP exchange is played by respx with the response shapes seen on a Databricks workspace on
2026-10-12 (config overrides.prefix, LoadTable metadata-location / storage-credentials)."""

from __future__ import annotations

import httpx
import pytest
import respx

from provisa.core.models import Source, SourceType
from provisa.federation.databricks_iceberg_resolver import (
    StorageCredential,
    resolve_databricks_iceberg_table,
    s3_secret_options,
)

pytestmark = pytest.mark.unit

_HOST = "acme.cloud.databricks.com"
_BASE = f"https://{_HOST}/api/2.1/unity-catalog/iceberg-rest/v1"
_TABLE = f"{_BASE}/catalogs/ext/namespaces/itest/tables/people"
_METADATA = "s3://bucket/uc/ext/itest/people/metadata/00002-abc.metadata.json"


def _src(**kw) -> Source:
    return Source(
        id=kw.pop("id", "dbx"),
        type=SourceType.databricks,
        host=kw.pop("host", _HOST),
        password=kw.pop("password", "dapiTOKEN"),
        database=kw.pop("database", "ext"),
        federation_hints=kw.pop(
            "federation_hints", {"schema": "itest", "table": "people", "reach": "scan"}
        ),
        **kw,
    )


def _credential(prefix: str = "s3://bucket/uc/ext", **config: str) -> dict:
    base = {
        "s3.access-key-id": "ASIAKEY",
        "s3.secret-access-key": "secret",
        "s3.session-token": "token",
        "client.region": "us-east-2",
    }
    base.update(config)
    return {"prefix": prefix, "config": base}


def _config_route() -> respx.Route:
    return respx.get(f"{_BASE}/config", params={"warehouse": "ext"}).mock(
        return_value=httpx.Response(200, json={"overrides": {"prefix": "catalogs/ext"}})
    )


@respx.mock
def test_the_table_and_its_vended_credentials_are_read_from_the_iceberg_rest_catalog():
    _config_route()
    load = respx.get(_TABLE).mock(
        return_value=httpx.Response(
            200,
            json={
                "metadata-location": _METADATA,
                "metadata": {},
                "config": {},
                "storage-credentials": [_credential()],
            },
        )
    )
    table = resolve_databricks_iceberg_table(_src())
    assert table.metadata_location == _METADATA
    assert table.credentials == (StorageCredential("s3://bucket/uc/ext", _credential()["config"]),)
    request = load.calls.last.request
    assert request.headers["X-Iceberg-Access-Delegation"] == "vended-credentials"
    assert request.headers["Authorization"] == "Bearer dapiTOKEN"


@respx.mock
def test_every_call_reads_the_current_pointer():
    # Nothing is cached: two resolutions make two LoadTable calls and see the newer snapshot
    _config_route()
    newer = _METADATA.replace("00002", "00003")
    respx.get(_TABLE).mock(
        side_effect=[
            httpx.Response(
                200, json={"metadata-location": m, "storage-credentials": [_credential()]}
            )
            for m in (_METADATA, newer)
        ]
    )
    assert resolve_databricks_iceberg_table(_src()).metadata_location == _METADATA
    assert resolve_databricks_iceberg_table(_src()).metadata_location == newer


@respx.mock
@pytest.mark.parametrize("status", [400, 404])
def test_a_table_that_is_not_iceberg_fails_naming_it(status):
    _config_route()
    respx.get(_TABLE).mock(return_value=httpx.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(ValueError, match=r"no Iceberg table ext\.itest\.people.*UniForm"):
        resolve_databricks_iceberg_table(_src())


@respx.mock
def test_a_table_with_no_vended_credentials_fails_saying_what_the_workspace_needs():
    _config_route()
    respx.get(_TABLE).mock(
        return_value=httpx.Response(
            200, json={"metadata-location": _METADATA, "storage-credentials": []}
        )
    )
    with pytest.raises(ValueError, match=r"vended no storage credentials.*External data access"):
        resolve_databricks_iceberg_table(_src())


@respx.mock
def test_a_catalog_whose_config_names_no_prefix_fails():
    respx.get(f"{_BASE}/config", params={"warehouse": "ext"}).mock(
        return_value=httpx.Response(200, json={"defaults": {}, "overrides": {}})
    )
    with pytest.raises(ValueError, match="names no path prefix"):
        resolve_databricks_iceberg_table(_src())


@pytest.mark.parametrize(
    ("field", "kw"),
    [
        ("host", {"host": ""}),
        ("password", {"password": ""}),
        ("database", {"database": ""}),
        ("schema", {"federation_hints": {"table": "people"}}),
    ],
)
def test_a_source_missing_a_field_the_lookup_needs_fails_before_any_call(field, kw):
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(ValueError, match=field):
            resolve_databricks_iceberg_table(_src(**kw))
        assert not mock.calls


def test_a_vended_s3_credential_becomes_duckdb_secret_options():
    options = s3_secret_options(StorageCredential("s3://bucket/uc/ext", _credential()["config"]))
    assert options == {
        "KEY_ID": "ASIAKEY",
        "SECRET": "secret",
        "SCOPE": "s3://bucket/uc/ext",
        "SESSION_TOKEN": "token",
        "REGION": "us-east-2",
    }


def test_a_credential_that_is_not_s3_is_refused():
    with pytest.raises(ValueError, match="only s3:// storage"):
        s3_secret_options(StorageCredential("abfss://c@a.dfs.core.windows.net/x", {}))


def test_an_s3_credential_without_its_keys_is_refused():
    with pytest.raises(ValueError, match="s3.secret-access-key"):
        s3_secret_options(StorageCredential("s3://b/p", {"s3.access-key-id": "k"}))
