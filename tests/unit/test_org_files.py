# Copyright (c) 2026 Kenneth Stott
# Canary: 8e2c4a17-3b9d-4f60-a5c1-6d7e9b0f2a38
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Each org's folder on a node: the one place the files Provisa keeps for it go (REQ-1992)."""

from __future__ import annotations

import asyncio

import pytest

from provisa.core import org_files
from provisa.core.org_files import OrgFolderUnavailable


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVISA_DATA_DIR", str(tmp_path))
    return tmp_path


def test_a_folder_is_ready_once_the_orgs_runtime_prepares_it(data_dir, monkeypatch):
    with pytest.raises(OrgFolderUnavailable, match="'acme'"):
        org_files.org_root("acme")
    asyncio.run(org_files.prepare("acme"))
    assert org_files.org_root("acme") == data_dir / "orgs" / "acme"


def test_each_org_has_its_own_folder(data_dir, monkeypatch):
    for org in ("acme", "globex"):
        asyncio.run(org_files.prepare(org))
    assert org_files.org_root("acme") != org_files.org_root("globex")


def test_the_bound_orgs_folder_is_the_default(data_dir, bind_org, monkeypatch):
    bind_org("acme")
    asyncio.run(org_files.prepare("acme"))
    assert org_files.org_root() == data_dir / "orgs" / "acme"
    assert org_files.org_path("crawl", "wiki") == data_dir / "orgs" / "acme" / "crawl" / "wiki"


def test_temporary_files_are_made_in_the_orgs_folder(data_dir, bind_org, monkeypatch):
    bind_org("acme")
    asyncio.run(org_files.prepare("acme"))
    made = org_files.mkdtemp("x-")
    assert made.startswith(str(data_dir / "orgs" / "acme" / "tmp"))


def test_an_org_id_that_is_not_one_path_segment_never_becomes_a_path(data_dir, monkeypatch):
    with pytest.raises(ValueError):
        org_files.folder("../acme")
