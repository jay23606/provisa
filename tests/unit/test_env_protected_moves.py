# Copyright (c) 2026 Kenneth Stott
# Canary: cd58f562-b563-465c-a0bf-2e9d4c14d310
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Undo, redo and pull are checked like deploy (REQ-1496, REQ-1504, REQ-1543, REQ-1547).

All three apply a tree to an environment, so all three meet the same door a deploy meets: a
protected environment is proposed to, and the proposal is what somebody else decides. What is under
test here is that each endpoint asks the question before it applies; the request itself and its
decision are covered in ``tests/integration/test_env_deploy_approvals.py``.
"""

# Requirements: REQ-1496, REQ-1504, REQ-1543, REQ-1547

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from provisa.api.admin import environments_router as er
from provisa.core import env_approvals, env_ci, env_repo, secrets_store
from provisa.core.env_deploy import DeployDelta, DeployReport

pytestmark = pytest.mark.asyncio

ORG = "acme"
FIRST = "a" * 40
SECOND = "b" * 40
THIRD = "c" * 40
REMOTE = "d" * 40


class _Request:
    class state:  # noqa: N801 -- mirrors starlette's attribute name
        identity = None


def _report(env: str, ref: str) -> DeployReport:
    return DeployReport(env, ref, False, DeployDelta(removed=["sales/tables/Order.yaml"]))


@pytest.fixture
def wired(monkeypatch):
    """Every collaborator replaced and recorded; ``prod`` is the protected environment."""
    calls: dict[str, list] = {k: [] for k in ("deploy", "request", "position", "audit", "land")}
    rows = {
        "prod": {"name": "prod", "deployed_sha": SECOND, "redo_sha": THIRD, "origin_sha": None},
        "dev": {"name": "dev", "deployed_sha": SECOND, "redo_sha": THIRD, "origin_sha": None},
    }

    async def _guard_within(request, org_id, name):
        return "uid-owner"

    async def _known(org_id, name):
        return rows[name]

    async def _audit(org_id, actor, action, name, detail):
        calls["audit"].append((action, name, detail))

    async def _org_model_db(org_id):
        return "tenant-db"

    async def _member_count(org_id):
        return 4

    async def _refresh(org_id, env, *, connectivity):
        return "uncached"

    async def _land(org_id, name, sha, actor):
        calls["land"].append((name, sha))
        return sha

    async def _remote_of(org_id):
        return "https://git.example/acme.git"

    async def is_protected(admin_db, org_id, name, member_count):
        return name == "prod"

    async def deploy_tree(db, org_id, env, tree, *, ref, seed=False, base_sha=None):
        calls["deploy"].append((env, ref))
        return _report(env, ref)

    async def plan_deploy(db, org_id, env, tree, *, ref, seed=False, base_sha=None):
        calls.setdefault("plan", []).append((env, ref))
        return _report(env, ref)

    monkeypatch.setattr(er, "plan_deploy", plan_deploy)

    async def request_deploy(admin_db, tenant_db, org_id, **kw):
        calls["request"].append(kw)
        return {"id": 7, "target_env": kw["target_env"], "report": _report("prod", "x").as_dict()}

    async def set_position(db, org_id, name, *, deployed_sha, deployed_stamp, redo_sha):
        calls["position"].append((name, deployed_sha, redo_sha))

    @asynccontextmanager
    async def _bound(_admin_db, _org_id, *, user_id=None):
        yield

    from provisa.api.admin import orgs_router

    monkeypatch.setattr(er, "_guard_within", _guard_within)
    monkeypatch.setattr(er, "_known", _known)
    monkeypatch.setattr(er, "_audit", _audit)
    monkeypatch.setattr(er, "_member_count", _member_count)
    monkeypatch.setattr(er, "_refresh", _refresh)
    monkeypatch.setattr(er, "_remote_of", _remote_of)
    monkeypatch.setattr(er, "_land", _land)
    monkeypatch.setattr(er, "_admin_pool", lambda: "admin-db")
    monkeypatch.setattr(er, "deploy_tree", deploy_tree)
    monkeypatch.setattr(env_approvals, "is_protected", is_protected)
    monkeypatch.setattr(env_approvals, "request_deploy", request_deploy)
    monkeypatch.setattr("provisa.core.env_store.set_position", set_position)
    monkeypatch.setattr(orgs_router, "_org_model_db", _org_model_db)
    monkeypatch.setattr(secrets_store, "bound", _bound)
    monkeypatch.setattr(env_ci, "fetch", lambda org_id, remote: None)
    monkeypatch.setattr(env_repo, "parent_of", lambda org_id, sha: FIRST)
    monkeypatch.setattr(env_repo, "step_toward", lambda org_id, here, top: THIRD)
    monkeypatch.setattr(env_repo, "merge_base", lambda org_id, a, b: SECOND)
    monkeypatch.setattr(
        env_repo, "files_at", lambda org_id, sha: {"sources/warehouse.yaml": "type: postgres\n"}
    )
    monkeypatch.setattr(
        env_repo,
        "sync_state",
        lambda org_id, env: {
            "local": SECOND,
            "remote": REMOTE,
            "ahead": 0,
            "behind": 1,
            "diverged": False,
            "unsynced": True,
        },
    )
    return calls


def _proposed(out: dict, calls: dict, sha: str) -> None:
    assert calls["deploy"] == []
    assert calls["position"] == []
    assert out["applied"] is False and out["requires_approval"] is True
    assert out["request"]["id"] == 7
    (kw,) = calls["request"]
    assert kw["sha"] == sha
    assert kw["target_env"] == "prod"
    assert kw["requested_by"] == "uid-owner"
    assert kw["seed"] is False
    ((action, name, detail),) = calls["audit"]
    assert action == "environment.deploy_requested"
    assert name == "prod" and detail["request_id"] == 7


class TestAProtectedEnvironmentIsProposedTo:
    async def test_an_undo_becomes_a_request(self, wired):
        out = await er.undo_environment(_Request(), ORG, "prod")
        _proposed(out, wired, FIRST)

    async def test_a_redo_becomes_a_request(self, wired):
        out = await er.redo_environment(_Request(), ORG, "prod")
        _proposed(out, wired, THIRD)

    async def test_a_pull_becomes_a_request(self, wired):
        out = await er.pull_environment(_Request(), ORG, "prod")
        _proposed(out, wired, REMOTE)


class TestAnUnprotectedEnvironmentStillMoves:
    async def test_an_undo_applies(self, wired):
        out = await er.undo_environment(_Request(), ORG, "dev")
        assert wired["deploy"] == [("dev", FIRST)]
        assert wired["request"] == []
        assert out["deployed_sha"] == FIRST

    async def test_a_redo_applies(self, wired):
        await er.redo_environment(_Request(), ORG, "dev")
        assert wired["deploy"] == [("dev", THIRD)]
        assert wired["request"] == []

    async def test_a_pull_applies(self, wired):
        out = await er.pull_environment(_Request(), ORG, "dev")
        assert wired["deploy"] == [("dev", REMOTE)]
        assert wired["request"] == []
        assert out["applied"] is True

    async def test_a_pull_moves_the_branch_onto_the_commit_it_applied(self, wired):
        # REQ-1547: without this the tip never moves, the answer still reads "behind", and a
        # second pull applies the same commit again.
        await er.pull_environment(_Request(), ORG, "dev")
        assert wired["land"] == [("dev", REMOTE)]

    async def test_a_proposed_pull_moves_nothing(self, wired):
        await er.pull_environment(_Request(), ORG, "prod")
        assert wired["land"] == []


class TestARevertSaysWhatItWouldRemoveBeforeItApplies:
    """REQ-1496: a revert removes what the earlier build did not have, so those removals are named
    first -- before the step is taken, and first in its report."""

    async def test_a_dry_run_plans_the_step_and_moves_nothing(self, wired):
        out = await er.undo_environment(_Request(), ORG, "dev", dry_run=True)
        assert wired["plan"] == [("dev", FIRST)]
        assert wired["deploy"] == [] and wired["position"] == [] and wired["request"] == []
        assert out["applied"] is False
        assert (out["deployed_sha"], out["would_deploy"]) == (SECOND, FIRST)

    async def test_the_removals_lead_the_report(self, wired):
        out = await er.undo_environment(_Request(), ORG, "dev", dry_run=True)
        assert next(iter(out["report"]["removed"])) == "sales/tables/Order.yaml"
        keys = [k for k in out["report"] if k in ("added", "changed", "removed")]
        assert keys[0] == "removed"

    async def test_a_dry_run_against_a_protected_environment_proposes_nothing(self, wired):
        out = await er.redo_environment(_Request(), ORG, "prod", dry_run=True)
        assert wired["request"] == [] and wired["audit"] == []
        assert out["requires_approval"] is True
