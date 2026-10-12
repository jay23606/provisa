# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A code source's uploads (REQ-1984, REQ-1993): an archive is kept by the content hash of the code
it unpacks to and a lockfile by the SHA-256 of its bytes, each in the organisation's store; an
archive that cannot be used, an empty upload and one past the bound are refused by name, and
nothing is kept for them."""

# Requirements: REQ-1984, REQ-1993
from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from provisa.api.admin import code_uploads_router
from provisa.api.errors import ApiError
from provisa.codesource import uploads
from provisa.codesource.bundle import content_hash, unpack

pytestmark = pytest.mark.unit


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def plane(tmp_path):
    from provisa.core import schema_admin
    from provisa.core.database import Database, create_engine_from_url

    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'plane.db'}")
    with engine.begin() as conn:
        schema_admin.metadata.create_all(
            conn, tables=[schema_admin.orgs, schema_admin.org_code_bundles]
        )
    yield Database(engine, name="admin")
    engine.dispose()


@pytest.fixture
def client(plane, monkeypatch):
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(code_uploads_router, "_admin_pool", lambda: plane)
    app = FastAPI()

    @app.exception_handler(ApiError)
    async def _coded(_request, exc: ApiError):
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status_code)

    app.include_router(code_uploads_router.router)
    return TestClient(app)


async def test_an_archive_is_kept_by_its_codes_content_hash(client, plane, tmp_path):
    data = _zip({"rates/rates.py": b"def rate():\n    return 1\n"})
    answer = client.post("/admin/orgs/acme/code-uploads/archive?filename=rates.zip", content=data)
    assert answer.status_code == 200, answer.text
    expected = content_hash(unpack("rates.zip", data, tmp_path / "x"))
    assert answer.json() == {"content_hash": expected, "filename": "rates.zip"}
    assert (await uploads.read(plane, "acme", expected)).data == data


async def test_a_lockfile_is_kept_by_the_sha256_of_its_bytes(client, plane):
    data = b"six==1.16.0 --hash=sha256:aa\n"
    answer = client.post(
        "/admin/orgs/acme/code-uploads/lockfile?filename=requirements.txt", content=data
    )
    assert answer.json() == {
        "sha256": hashlib.sha256(data).hexdigest(),
        "filename": "requirements.txt",
    }
    assert await uploads.read_file(plane, "acme", hashlib.sha256(data).hexdigest()) == data


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (_zip({"../escape.py": b"x"}), 400, "codesource.archive_escapes"),
        (b"", 400, "codesource.upload_empty"),
    ],
)
def test_an_upload_that_cannot_be_kept_is_refused_by_name(client, data, status, code):
    answer = client.post("/admin/orgs/acme/code-uploads/archive?filename=rates.zip", content=data)
    assert (answer.status_code, answer.json()["code"]) == (status, code)


def test_an_upload_past_the_bound_is_refused(client, monkeypatch):
    monkeypatch.setattr(code_uploads_router, "MAX_UPLOAD_BYTES", 4)
    answer = client.post(
        "/admin/orgs/acme/code-uploads/lockfile?filename=uv.lock", content=b"12345"
    )
    assert (answer.status_code, answer.json()["code"]) == (413, "codesource.upload_too_large")
