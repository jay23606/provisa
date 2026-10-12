# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Amazon Athena direct source driver (REQ-1981).

Athena is a named source reached through its own API (PyAthena, over boto3): a statement on its
tables alone runs whole in Athena, its filters, columns and limits with it, so the bytes Athena
scans and bills are the statement's own. Every other engine reads a replica it lands.

The connection is the source's own (``database`` = the Glue database queried by default;
``federation_hints`` carries ``region``, ``workgroup``, ``s3_staging_dir``, ``catalog`` and
``role_arn``). The access key pair is the source's ``username``/``password``, each resolved at use;
with none, boto3's own credential chain is used (an instance role, the environment, a profile), as
for the mail service's SES (``core/mail.py``). A role ARN, when given, is assumed for every call.
"""

# Requirements: REQ-1981

from __future__ import annotations

import asyncio
from typing import Any

import pyathena  # the driver's dependency: imported here, so its absence means no driver

from provisa.executor.drivers.base import DirectDriver
from provisa.executor.result import QueryResult

#: The hints a source may set, beside its region.
_OPTIONAL = ("workgroup", "s3_staging_dir", "catalog", "role_arn")


def _to_pyformat(sql: str, params: list | None) -> tuple[str, dict[str, Any] | None]:
    """``$N`` placeholders as PyAthena's ``%(pN)s`` (highest index first, so ``$1`` does not
    corrupt ``$10``); a literal ``%`` is doubled, since the driver formats the statement."""
    if not params:
        return sql, None
    out = sql.replace("%", "%%")
    bind: dict[str, Any] = {}
    for i in range(len(params), 0, -1):
        out = out.replace(f"${i}", f"%(p{i})s")
        bind[f"p{i}"] = params[i - 1]
    return out, bind


class AthenaDriver(DirectDriver):
    def __init__(self) -> None:
        self._conn: Any = None
        self._extra: dict[str, str] = {}

    def configure(self, extra: dict[str, str]) -> None:
        """The source's ``region`` (required), and its optional ``workgroup``,
        ``s3_staging_dir`` (where Athena writes results, unless the workgroup sets it),
        ``catalog`` (default ``AwsDataCatalog``) and ``role_arn``."""
        self._extra = dict(extra)

    async def connect(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        host: str,  # pyright: ignore[reportUnusedParameter]
        port: int,  # pyright: ignore[reportUnusedParameter]
        database: str,
        user: str,
        password: str,
        min_pool: int = 1,  # pyright: ignore[reportUnusedParameter]
        max_pool: int = 5,  # pyright: ignore[reportUnusedParameter]
    ) -> None:
        region = self._extra.get("region")
        if not region:
            raise ValueError("athena source requires its region (federation hint `region`)")
        if bool(user) != bool(password):
            raise ValueError(
                "athena source: an access key ID and its secret are given together, or neither "
                "(for the AWS credential chain)"
            )
        kwargs: dict[str, Any] = {"region_name": region, "schema_name": database or "default"}
        for key, arg in zip(
            _OPTIONAL, ("work_group", "s3_staging_dir", "catalog_name", "role_arn")
        ):
            if self._extra.get(key):
                kwargs[arg] = self._extra[key]
        if user:
            kwargs["aws_access_key_id"] = user
            kwargs["aws_secret_access_key"] = password

        def _open() -> Any:
            return pyathena.connect(**kwargs)

        self._conn = await asyncio.to_thread(_open)

    async def execute(self, sql: str, params: list | None = None) -> QueryResult:
        statement, bind = _to_pyformat(sql, params)

        def _run() -> QueryResult:
            cursor = self._conn.cursor()
            try:
                cursor.execute(statement, bind)
                if cursor.description is None:
                    count = cursor.rowcount
                    return QueryResult(
                        rows=[], column_names=[], rowcount=count if count >= 0 else None
                    )
                cols = [d[0] for d in cursor.description]
                return QueryResult(rows=[tuple(r) for r in cursor.fetchall()], column_names=cols)
            finally:
                cursor.close()

        return await asyncio.to_thread(_run)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None
