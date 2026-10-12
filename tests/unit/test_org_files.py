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
    # This node's own temporary directory in the org's folder (REQ-1992: nodes share the mount).
    assert made.startswith(str(data_dir / "orgs" / "acme" / "nodes" / org_files.node_id() / "tmp"))


def test_an_org_id_that_is_not_one_path_segment_never_becomes_a_path(data_dir, monkeypatch):
    with pytest.raises(ValueError):
        org_files.folder("../acme")


def test_what_one_process_keeps_is_in_the_nodes_own_subtree(data_dir, bind_org, monkeypatch):
    """REQ-1992: nodes sharing the mount never write each other's run directories, spools or
    temporary files."""
    monkeypatch.setenv("PROVISA_ORG_FILES_NODE_ID", "pod-a")
    bind_org("acme")
    asyncio.run(org_files.prepare("acme"))
    own = data_dir / "orgs" / "acme" / "nodes" / "pod-a"
    assert org_files.org_tmp() == own / "tmp"
    assert org_files.node_path("pgwire", "1.0", "src") == own / "pgwire" / "1.0" / "src"


@pytest.mark.parametrize("name", ["../pod", "pod/a", ".hidden"])
def test_a_node_name_that_is_not_one_path_segment_is_refused(monkeypatch, name):
    monkeypatch.setenv("PROVISA_ORG_FILES_NODE_ID", name)
    with pytest.raises(ValueError, match="one path segment"):
        org_files.node_id()


def test_the_spool_sweep_reaches_only_this_nodes_spools(data_dir, bind_org, monkeypatch):
    from provisa.federation.replica_spool import node_spool_directories

    monkeypatch.setenv("PROVISA_ORG_FILES_NODE_ID", "pod-a")
    for node in ("pod-a", "pod-b"):
        (data_dir / "orgs" / "acme" / "nodes" / node / "replica-spool").mkdir(parents=True)
    assert node_spool_directories() == [
        data_dir / "orgs" / "acme" / "nodes" / "pod-a" / "replica-spool"
    ]


def test_the_embedded_duckdb_store_is_refused_on_a_shared_mount(data_dir, monkeypatch):
    from provisa.federation.engine import EmbeddedStoreOnSharedMount, embedded_store_dsn

    monkeypatch.setenv("PROVISA_ORG_FILES_SHARED_MOUNT", "true")
    asyncio.run(org_files.prepare("acme"))
    with pytest.raises(EmbeddedStoreOnSharedMount, match="materialize_store_url"):
        embedded_store_dsn("acme")
