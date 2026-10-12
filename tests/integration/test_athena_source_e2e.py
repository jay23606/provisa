# Copyright (c) 2026 Kenneth Stott
# Canary: cebff8e1-edf4-4f04-8753-7af9b37c5f9c
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A live Amazon Athena source (REQ-1981): its catalog through the metadata API, and reads and
writes through its driver.

Each run makes its own Glue database, ``provisa_itest_<run>``, holding a Hive table over a CSV it
writes under ``itest/<run>/`` of the test bucket, and an Iceberg table; everything it makes is
dropped and deleted whether the run passes or fails. It reads ATHENA_REGION and ATHENA_S3_BUCKET,
and ATHENA_AWS_ACCESS_KEY_ID / ATHENA_AWS_SECRET_ACCESS_KEY when set (else boto3's credential
chain, as a source with no key pair has).
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_athena,
    pytest.mark.requires_warehouse,
    pytest.mark.asyncio(loop_scope="session"),
]

_RUN = uuid.uuid4().hex[:8]
_DB = f"provisa_itest_{_RUN}"
_PREFIX = f"itest/{_RUN}"


def _hints() -> dict[str, str]:
    return {
        "region": os.environ["ATHENA_REGION"],
        "s3_staging_dir": f"s3://{os.environ['ATHENA_S3_BUCKET']}/results/",
    }


def _key_pair() -> tuple[str, str]:
    return (
        os.environ.get("ATHENA_AWS_ACCESS_KEY_ID", ""),
        os.environ.get("ATHENA_AWS_SECRET_ACCESS_KEY", ""),
    )


def _source():
    key, secret = _key_pair()
    return SimpleNamespace(
        id="athena-itest", federation_hints=_hints(), username=key, password=secret
    )


def _s3():
    import boto3

    key, secret = _key_pair()
    kwargs = {"aws_access_key_id": key, "aws_secret_access_key": secret} if key else {}
    return boto3.client("s3", region_name=os.environ["ATHENA_REGION"], **kwargs)


@pytest_asyncio.fixture(loop_scope="session", scope="module")
async def driver():
    """The driver, connected, over a database of this run's own: a Hive table ``pets`` and an
    Iceberg table ``notes``."""
    from provisa.executor.drivers.athena import AthenaDriver

    bucket = os.environ["ATHENA_S3_BUCKET"]
    s3 = _s3()
    s3.put_object(
        Bucket=bucket, Key=f"{_PREFIX}/pets/pets.csv", Body=b"1,rex,dog\n2,tom,cat\n3,ada,dog\n"
    )
    d = AthenaDriver()
    d.configure(_hints())
    await d.connect("", 0, "default", *_key_pair())
    try:
        await d.execute(f"CREATE DATABASE {_DB}")
        await d.execute(
            f"CREATE EXTERNAL TABLE {_DB}.pets (id int, name string, kind string) "
            "ROW FORMAT DELIMITED FIELDS TERMINATED BY ',' "
            f"LOCATION 's3://{bucket}/{_PREFIX}/pets/'"
        )
        await d.execute(
            f"CREATE TABLE {_DB}.notes (id int, body string) "
            f"LOCATION 's3://{bucket}/{_PREFIX}/notes/' TBLPROPERTIES ('table_type'='ICEBERG')"
        )
        yield d
    finally:
        for statement in (
            f"DROP TABLE IF EXISTS {_DB}.notes",
            f"DROP TABLE IF EXISTS {_DB}.pets",
            f"DROP DATABASE IF EXISTS {_DB}",
        ):
            await d.execute(statement)
        await d.close()
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=f"{_PREFIX}/").get("Contents", [])
        for obj in listed:
            s3.delete_object(Bucket=bucket, Key=obj["Key"])


async def test_its_catalog_is_read_through_the_metadata_api(driver):
    from provisa.federation import athena

    del driver
    assert _DB in athena.databases(_source())
    listed = {t.name: t.table_format for t in athena.tables(_source(), _DB)}
    assert listed == {"pets": "hive", "notes": "iceberg"}
    assert athena.columns(_source(), _DB, "pets") == [
        ("id", "integer"),
        ("name", "text"),
        ("kind", "text"),
    ]


async def test_a_table_is_read_with_a_filter_a_parameter_and_a_limit(driver):
    result = await driver.execute(
        f"SELECT name FROM {_DB}.pets WHERE kind = $1 ORDER BY id LIMIT 5", ["dog"]
    )
    assert result.rows == [("rex",), ("ada",)]


async def test_an_iceberg_table_is_inserted_updated_and_deleted(driver):
    inserted = await driver.execute(f"INSERT INTO {_DB}.notes VALUES (1, 'a'), (2, 'b')")
    assert inserted.rowcount == 2
    updated = await driver.execute(f"UPDATE {_DB}.notes SET body = $1 WHERE id = $2", ["z", 2])
    assert updated.rowcount == 1
    await driver.execute(f"DELETE FROM {_DB}.notes WHERE id = 1")
    assert (await driver.execute(f"SELECT id, body FROM {_DB}.notes")).rows == [(2, "z")]
