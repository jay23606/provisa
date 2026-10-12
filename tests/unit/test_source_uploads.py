# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1997: a file-based source's file, given by upload -- kept in the org's folder under
files/<source>/, streamed to disk, replacing the earlier one whole, refused over the operator's
limit, and removed with its source."""

from __future__ import annotations

import pytest

import provisa.core.settings_catalog  # noqa: F401 -- declares the settings read here
from provisa.core import org_files, source_uploads


@pytest.fixture
def org(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVISA_DATA_DIR", str(tmp_path / "data"))
    org_files.folder("acme").mkdir(parents=True)
    return "acme"


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


async def test_an_upload_is_kept_in_the_org_folder_and_named_by_its_source(org):
    path, size = await source_uploads.receive(
        "survey", "survey.sqlite", _chunks(b"abc", b"def"), 6, org_id=org
    )
    assert path == org_files.folder(org) / "files" / "survey" / "survey.sqlite"
    assert path.read_bytes() == b"abcdef" and size == 6
    assert source_uploads.is_upload("survey", str(path), org_id=org)
    assert not source_uploads.is_upload("survey", "/elsewhere/survey.sqlite", org_id=org)


async def test_a_new_upload_replaces_the_old_one_whole(org):
    first, _ = await source_uploads.receive("s", "a.csv", _chunks(b"1"), None, org_id=org)
    second, _ = await source_uploads.receive("s", "b.csv", _chunks(b"22"), None, org_id=org)
    assert not first.exists() and second.read_bytes() == b"22"
    assert sorted(p.name for p in second.parent.iterdir()) == ["b.csv"]


async def test_a_file_over_the_limit_is_refused_naming_it_and_nothing_is_kept(org, monkeypatch):
    monkeypatch.setenv("PROVISA_SOURCES_MAX_UPLOAD_BYTES", "4")
    with pytest.raises(source_uploads.UploadTooLarge) as declared:
        await source_uploads.receive("s", "a.csv", _chunks(b"12345"), 5, org_id=org)
    assert declared.value.params == {"limit": 4} and "4 bytes" in str(declared.value)
    # One that says nothing of its size is stopped when it passes the limit.
    with pytest.raises(source_uploads.UploadTooLarge):
        await source_uploads.receive("s", "a.csv", _chunks(b"123", b"45"), None, org_id=org)
    assert list((org_files.folder(org) / "files" / "s").iterdir()) == []


async def test_an_earlier_upload_survives_a_refused_one(org, monkeypatch):
    kept, _ = await source_uploads.receive("s", "a.csv", _chunks(b"ok"), None, org_id=org)
    monkeypatch.setenv("PROVISA_SOURCES_MAX_UPLOAD_BYTES", "2")
    with pytest.raises(source_uploads.UploadTooLarge):
        await source_uploads.receive("s", "a.csv", _chunks(b"too big"), None, org_id=org)
    assert kept.read_bytes() == b"ok"


@pytest.mark.parametrize("name", ["../x.csv", "a/b.csv", ".upload-x", "", "-x"])
async def test_a_name_that_is_not_one_file_name_is_refused(org, name):
    with pytest.raises(source_uploads.UploadRefused, match="cannot be the"):
        await source_uploads.receive("s", name, _chunks(b"x"), None, org_id=org)


async def test_removing_the_source_removes_its_upload(org):
    path, _ = await source_uploads.receive("s", "a.csv", _chunks(b"x"), None, org_id=org)
    source_uploads.remove("s", org_id=org)
    assert not path.parent.exists()
    source_uploads.remove("s", org_id=org)  # nothing left to remove


async def test_an_org_folder_not_ready_refuses_the_upload_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVISA_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(org_files.OrgFolderUnavailable, match="nobody"):
        await source_uploads.receive("s", "a.csv", _chunks(b"x"), None, org_id="nobody")
