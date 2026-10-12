# Copyright (c) 2026 Kenneth Stott
# Canary: 760cf319-f864-425d-b805-c409ce4e9b53
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Resolve a Databricks Unity Catalog table's live Iceberg metadata, with the storage credentials to
read it (REQ-1867).

Unity Catalog serves the Apache Iceberg REST catalog at ``/api/2.1/unity-catalog/iceberg-rest``
for any table that is native Iceberg or has UniForm Iceberg enabled. (The older
``/api/2.1/unity-catalog/iceberg/v1`` endpoint answers HTTP 400 "deprecated" since 2026; #243.)
``GET /v1/config?warehouse=<catalog>`` gives the path prefix for the catalog; ``LoadTable`` under
it answers with the table's CURRENT ``metadata-location``, the pointer DuckDB's ``iceberg_scan``
reads the live snapshot from, in place. Asked with ``X-Iceberg-Access-Delegation:
vended-credentials``, it also returns temporary credentials for the table's storage; nothing
outside Databricks can read that storage without them.

Nothing here is cached: every call reads the current pointer and fresh credentials. Auth follows
``provisa.executor.drivers.databricks.DatabricksDriver``: a bearer token carried as the source's
``password``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

import httpx

if TYPE_CHECKING:
    from provisa.core.models import Source


@dataclass(frozen=True)
class StorageCredential:
    """Temporary credentials Unity Catalog vended for the storage under ``prefix``."""

    prefix: str
    config: Mapping[str, str]


@dataclass(frozen=True)
class DatabricksIcebergTable:
    metadata_location: str
    credentials: tuple[StorageCredential, ...]


def _required(source: "Source") -> tuple[str, str]:
    """The schema and table of ``source``, after checking every field the lookup needs. None has a
    sane default; guessing one would point ``iceberg_scan`` at the wrong table."""
    if not source.host:
        raise ValueError(f"databricks source {source.id!r} requires 'host' (workspace hostname)")
    if not source.password:
        raise ValueError(
            f"databricks source {source.id!r} requires 'password' (Databricks personal access token)"
        )
    if not source.database:
        raise ValueError(
            f"databricks source {source.id!r} requires 'database' (Unity Catalog catalog name)"
        )
    schema = source.federation_hints.get("schema")
    table = source.federation_hints.get("table")
    if not schema or not table:
        raise ValueError(
            f"databricks source {source.id!r} requires 'schema' and 'table' in federation_hints"
        )
    return schema, table


def resolve_databricks_iceberg_table(source: "Source") -> DatabricksIcebergTable:
    """The table's current Iceberg ``metadata-location`` and the storage credentials Unity Catalog
    vends for it. A table that is neither native Iceberg nor UniForm, or a catalog that vends no
    credentials (external data access off, or no EXTERNAL USE SCHEMA on the schema), raises here,
    naming the table."""
    schema, table = _required(source)
    base = f"https://{source.host}/api/2.1/unity-catalog/iceberg-rest/v1"
    auth = {"Authorization": f"Bearer {source.password}"}
    name = f"{source.database}.{schema}.{table}"

    config = httpx.get(
        f"{base}/config", params={"warehouse": source.database}, headers=auth, timeout=10.0
    )
    config.raise_for_status()
    body = config.json()
    prefix = (body.get("overrides") or {}).get("prefix") or (body.get("defaults") or {}).get(
        "prefix"
    )
    if not prefix:
        raise ValueError(
            f"databricks source {source.id!r}: the Iceberg REST config for catalog "
            f"{source.database!r} names no path prefix"
        )

    resp = httpx.get(
        f"{base}/{prefix}/namespaces/{schema}/tables/{table}",
        headers={**auth, "X-Iceberg-Access-Delegation": "vended-credentials"},
        timeout=10.0,
    )
    if resp.status_code in (400, 404):
        raise ValueError(
            f"databricks source {source.id!r}: Unity Catalog has no Iceberg table {name} "
            f"(HTTP {resp.status_code}: {resp.text[:300]}). Only native Iceberg tables and tables "
            "with UniForm Iceberg enabled can be read in place."
        )
    resp.raise_for_status()
    loaded = resp.json()
    metadata_location = loaded.get("metadata-location")
    if not metadata_location:
        raise ValueError(
            f"databricks source {source.id!r}: the Iceberg REST answer for {name} has no "
            "'metadata-location'"
        )
    credentials = tuple(
        StorageCredential(prefix=c["prefix"], config=dict(c.get("config") or {}))
        for c in loaded.get("storage-credentials") or ()
    )
    if not credentials:
        raise ValueError(
            f"databricks source {source.id!r}: Unity Catalog vended no storage credentials for "
            f"{name}, so its files cannot be read outside Databricks. The metastore needs "
            "'External data access' enabled, the table must be on storage Unity Catalog can vend "
            "for (not Databricks default storage), and the source's token needs EXTERNAL USE "
            "SCHEMA on the schema."
        )
    return DatabricksIcebergTable(metadata_location, credentials)


def s3_secret_options(credential: StorageCredential) -> dict[str, str]:
    """The DuckDB s3 secret options for a vended S3 credential, keyed by DuckDB's option names.
    A credential that is not S3 (an ADLS SAS token, a GCS OAuth token) raises: no engine here
    emits a secret for it yet."""
    config = credential.config
    if not credential.prefix.startswith("s3://"):
        raise ValueError(
            f"Unity Catalog vended a credential for {credential.prefix!r}; only s3:// storage "
            "is read in place"
        )
    missing = [k for k in ("s3.access-key-id", "s3.secret-access-key") if not config.get(k)]
    if missing:
        raise ValueError(
            f"the vended credential for {credential.prefix!r} lacks {', '.join(missing)}"
        )
    options = {
        "KEY_ID": config["s3.access-key-id"],
        "SECRET": config["s3.secret-access-key"],
        "SCOPE": credential.prefix,
    }
    if config.get("s3.session-token"):
        options["SESSION_TOKEN"] = config["s3.session-token"]
    region = config.get("client.region") or config.get("s3.region")
    if region:
        options["REGION"] = region
    return options
