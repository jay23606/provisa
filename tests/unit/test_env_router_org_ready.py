# Copyright (c) 2026 Kenneth Stott
# Canary: 07101b98-8273-4609-adfa-b3cbfe3f9709
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-1992, REQ-1546: an organization's environments are served only once the org is served on
this node -- its runtime built, which readies its folder, where its environments' repository
lives.

The UI e2e Trino lane failed on v0.1.0-alpha.480 and .481: its server serves org ``e2e_trino``,
and the UI's environment badge asked it about org ``e2e`` (``/-/repo-integration/sync``), an org
whose runtime that node had never built. Since REQ-1992 moved the repository into the org's
folder, which only a runtime build readies, the read answered 500 (OrgFolderUnavailable), and
every spec that rendered the badge failed on the uncaught browser error."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from provisa.api.admin import environments_router as er
from provisa.core import env_ci, env_repo, org_files
from provisa.core.env_ci import RepoIntegration

OTHER = "other_org"  # an org this node has not built a runtime for


def test_an_org_whose_folder_is_not_ready_has_no_repository_to_read():
    """The failure, as it was: the repository of an org not served on this node is refused."""
    with pytest.raises(org_files.OrgFolderUnavailable, match=OTHER):
        env_repo.branches(OTHER)


@pytest.fixture
def client(monkeypatch):
    readied: list[str] = []

    async def _ensure_org_runtime(org_id, env=None):
        # what a runtime build does for the folder (org_files.prepare, no admin plane)
        org_files.folder(org_id).mkdir(parents=True, exist_ok=True)
        readied.append(org_id)

    async def _member(request, org_id, *rights):
        return "uid-member"

    async def _read_integration(admin_db, org_id):
        return RepoIntegration()

    monkeypatch.setattr("provisa.api.app.ensure_org_runtime", _ensure_org_runtime)
    monkeypatch.setattr(er, "_member", _member)
    monkeypatch.setattr(er, "_admin_pool", lambda: "admin-db")
    monkeypatch.setattr(env_ci, "read_integration", _read_integration)
    app = FastAPI()
    app.include_router(er.router)
    return TestClient(app), readied


def test_an_orgs_environments_are_read_once_the_org_is_ready_on_this_node(client):
    http, readied = client
    resp = http.get(f"/admin/orgs/{OTHER}/environments/-/repo-integration/sync")
    assert resp.status_code == 200, resp.text
    assert readied == [OTHER]
    assert resp.json()["remote_configured"] is False


def test_every_environments_route_readies_the_org_first():
    """The dependency is the router's, so no route reaches the repository before it."""
    assert any(d.dependency is er._org_ready_on_this_node for d in er.router.dependencies)
