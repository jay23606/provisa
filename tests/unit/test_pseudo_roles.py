# Copyright (c) 2026 Kenneth Stott
# Canary: 96dd49e1-8cbe-4a56-921a-6903fde3e1c7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Pseudo-roles: roles held because of what a user's attributes say about a declared claim type
(REQ-2057). Rightless, never granted by hand, named by a request like any role, and entering a
meta-role through its grants only."""

# Requirements: REQ-2057

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from provisa.auth.middleware import AuthMiddleware
from provisa.auth.models import AuthIdentity, AuthProvider
from provisa.auth.pseudo_roles import (
    declared_claim_roles,
    held_pseudo_roles,
    principal_bindings,
    principal_session_vars,
)
from provisa.security import meta_role
from provisa.security.inheritance import expand_grants
from provisa.security.masking import MaskingRule, MaskType


class TestHolding:
    def test_a_declared_claim_gives_its_parent_and_the_sub_role_of_its_value(self):
        held = held_pseudo_roles(["region"], {"region": "eu", "department": "marketing"})
        assert held == {"region": "", "region__eu": "region"}

    def test_no_value_holds_neither_the_parent_nor_a_sub_role(self):
        assert held_pseudo_roles(["region"], {"department": "marketing"}) == {}
        assert held_pseudo_roles(["region"], {"region": ""}) == {}

    def test_the_orgs_record_decides_the_value(self):
        attributes, held = principal_bindings({"region": "us"}, {"region": "eu"}, ["Region"])
        assert attributes == {"region": "eu"}
        assert held == {"region": "", "region__eu": "region"}

    def test_the_orgs_own_list_replaces_the_deployments(self):
        config = SimpleNamespace(claim_roles=["region"])
        assert declared_claim_roles(SimpleNamespace(settings_overrides={}, config=config)) == [
            "region"
        ]
        org = SimpleNamespace(settings_overrides={"claim_roles": []}, config=config)
        assert declared_claim_roles(org) == []

    def test_session_variables_are_the_attributes_then_the_identity(self):
        assert principal_session_vars("u1", {"region": "eu", "role": "x"}, "analyst") == {
            "region": "eu",
            "user_id": "u1",
            "role": "analyst",
        }


class TestNaming:
    def test_a_named_pseudo_role_qualifies_the_set_with_its_parent(self, monkeypatch):
        built: list = []
        monkeypatch.setattr(
            meta_role,
            "ensure_meta_role",
            lambda _s, members, quals=(): built.append((members, quals)) or "meta:x",
        )
        held = {"region": "", "region__eu": "region"}
        assert (
            meta_role.resolve_requested_role(None, {"analyst"}, "analyst,region__eu", lambda: held)
            == "meta:x"
        )
        assert built == [(["analyst"], ("region", "region__eu"))]

    def test_the_pseudo_roles_are_read_only_when_a_named_role_is_not_assigned(self, monkeypatch):
        monkeypatch.setattr(meta_role, "ensure_meta_role", lambda _s, members: "meta:x")
        unread = lambda: pytest.fail("no named role is unassigned")  # noqa: E731
        assert meta_role.resolve_requested_role(None, {"analyst"}, "analyst", unread) == "analyst"

    def test_a_pseudo_role_not_held_is_refused_by_name(self):
        with pytest.raises(PermissionError, match="region__us"):
            meta_role.resolve_requested_role(
                None, {"analyst"}, "analyst,region__us", lambda: {"region__eu": "region"}
            )

    def test_named_with_no_data_role_it_reaches_no_data(self):
        state = SimpleNamespace(surfaces={"analyst": object()})
        with pytest.raises(PermissionError, match="No schema available"):
            meta_role.ensure_meta_role(state, [], ("region__eu",))


class TestTheMetaRole:
    def test_a_grant_to_a_qualifier_reaches_the_meta_role(self):
        meta = "meta:analyst+region+region__eu"
        col = {"column_name": "email", "unmasked_to": ["region__eu"], "visible_to": ["analyst"]}
        expand_grants([col], {meta: [meta, "analyst", "region", "region__eu"]})
        assert meta in col["unmasked_to"] and meta in col["visible_to"]

    def test_only_a_qualifiers_grant_lifts_a_mask_and_never_a_fake(self):
        meta = "meta:analyst+region__eu"
        mask = MaskingRule(mask_type=MaskType.constant, value=None)
        fake = MaskingRule(mask_type=MaskType.fake, fake="name")
        masks = {(1, meta): {"email": mask, "name": fake, "phone": mask}}
        tables = [
            {
                "id": 1,
                "columns": [
                    {"column_name": "email", "unmasked_to": ["region__eu", meta]},
                    {"column_name": "name", "unmasked_to": [meta]},
                    {"column_name": "phone", "unmasked_to": ["org_admin"]},
                ],
            }
        ]
        lifted = meta_role._lift_qualified(masks, tables, meta)
        assert set(lifted[(1, meta)]) == {"name", "phone"}

    def test_a_qualifier_is_no_member_of_the_mask_intersection(self):
        # As a member with no masks it would unmask every column the data members mask.
        mask = MaskingRule(mask_type=MaskType.constant, value=None)
        rules = {(1, "analyst"): {"email": mask}}
        assert meta_role.meta_masks(rules, "meta:m", ["analyst"]) == {
            (1, "meta:m"): {"email": mask}
        }


class _RegionProvider(AuthProvider):
    async def validate_token(self, token: str) -> AuthIdentity:
        if token != "t":
            raise ValueError("Invalid token")
        return AuthIdentity(
            user_id="amelie",
            email=None,
            display_name=None,
            roles=["analyst"],
            raw_claims={"region": "us"},
        )


@pytest.fixture
def client(monkeypatch, serve_deployment_org):
    # The middleware's deployment org is 'root'; the app state serves it (REQ-1266).
    serve_deployment_org("root")
    monkeypatch.setattr("provisa.auth.middleware._loaded_claim_roles", lambda: ["region"])
    monkeypatch.setattr(
        "provisa.auth.middleware._loaded_user_attributes", lambda _uid: {"region": "eu"}
    )
    monkeypatch.setattr(
        "provisa.security.meta_role.ensure_meta_role",
        lambda _s, members, quals=(): "meta:" + "+".join(sorted([*members, *quals])),
    )
    app = FastAPI()
    app.add_middleware(
        AuthMiddleware, provider=_RegionProvider(), default_role="analyst", default_org_id="root"
    )

    @app.get("/test")
    async def _t(request: Request):
        identity = request.state.identity
        return {
            "role": request.state.role,
            "pseudo": identity.pseudo_roles,
            "acting": identity.acting_roles,
        }

    return TestClient(app)


class TestTheRequest:
    def test_the_user_holds_what_the_orgs_record_says_and_acts_as_nothing_of_it_unnamed(
        self, client
    ):
        data = client.get("/test", headers={"Authorization": "Bearer t"}).json()
        assert data["pseudo"] == {"region": "", "region__eu": "region"}
        assert data["role"] == "analyst"

    def test_named_it_qualifies_the_acting_role_and_adds_no_right(self, client):
        resp = client.get(
            "/test", headers={"Authorization": "Bearer t", "X-Provisa-Role": "analyst,region__eu"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "meta:analyst+region+region__eu"
        assert resp.json()["acting"] == ["analyst"]

    def test_the_providers_value_is_not_held_where_the_org_says_otherwise(self, client):
        resp = client.get(
            "/test", headers={"Authorization": "Bearer t", "X-Provisa-Role": "analyst,region__us"}
        )
        assert resp.status_code == 403
        assert "region__us" in resp.json()["detail"]
