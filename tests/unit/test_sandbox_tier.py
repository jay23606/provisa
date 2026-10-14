# Copyright (c) 2026 Kenneth Stott
# Canary: 9be8110e-7f60-44e5-8a54-33886e82528d
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-2006: a demo sandbox's DuckDB file is opened by one process only -- the sandbox tier, which
serves the sandbox-tier orgs and nothing else -- and the UI server sends each request to the tier
that serves its org."""

# Requirements: REQ-2006

from __future__ import annotations

import pytest

from provisa.api.errors import ApiError
from provisa.api.sandbox_tier import (
    is_sandbox_tier_org,
    is_template_org,
    new_sandbox_org_id,
    require_this_tier,
    template_org_id,
)
from provisa.core.org_ids import is_org_id


def test_a_sandbox_and_a_template_are_org_ids_of_the_sandbox_tier_and_never_each_other():
    sandbox = new_sandbox_org_id()
    template = template_org_id("weblogs")
    assert is_org_id(sandbox) and is_org_id(template)
    assert is_sandbox_tier_org(sandbox) and is_sandbox_tier_org(template)
    assert is_template_org(template) and not is_template_org(sandbox)
    assert not is_sandbox_tier_org("acme") and not is_sandbox_tier_org("sandbox")
    assert len({new_sandbox_org_id() for _ in range(100)}) == 100


@pytest.mark.parametrize(
    ("tier", "org", "served"),
    [
        ("true", "sbx0123456789ab", True),
        ("true", "sbxtplweblogs", True),
        ("true", "acme", False),
        ("false", "acme", True),
        ("false", "sbx0123456789ab", False),
    ],
)
def test_each_tier_builds_its_own_orgs_only(monkeypatch, tier, org, served):
    monkeypatch.setenv("PROVISA_SANDBOX_TIER", tier)
    if served:
        require_this_tier(org)
        return
    with pytest.raises(ApiError) as refused:
        require_this_tier(org)
    assert refused.value.status_code == 421
    assert refused.value.code == "sandbox.wrong_tier"


def test_an_unset_tier_is_the_deployments_and_a_bad_value_is_refused(monkeypatch):
    monkeypatch.delenv("PROVISA_SANDBOX_TIER", raising=False)
    require_this_tier("acme")
    monkeypatch.setenv("PROVISA_SANDBOX_TIER", "yes")
    with pytest.raises(ValueError, match="PROVISA_SANDBOX_TIER"):
        require_this_tier("acme")


def test_the_ui_server_sends_a_sandbox_and_a_demo_opening_to_the_sandbox_tier(monkeypatch):
    import provisa.ui_server as ui_server

    monkeypatch.setattr(ui_server, "API_BASE_URL", "http://provisa:8000")
    monkeypatch.setattr(ui_server, "SANDBOX_API_URL", "http://provisa-sandbox:8000")
    main, tier = "http://provisa:8000", "http://provisa-sandbox:8000"
    route = ui_server.api_base_for
    assert route("data/sql", {"host": "sbx0123456789ab.provisa.dev"}) == tier
    assert (
        route("data/sql", {"host": "cloud.provisa.dev", "x-org-provisa": "sbxtplweblogs"}) == tier
    )
    assert route("public/demos/weblogs", {"host": "cloud.provisa.dev"}) == tier
    assert route("sandboxes/weblogs", {"host": "cloud.provisa.dev"}) == tier
    assert route("data/sql", {"host": "acme.provisa.dev"}) == main
    assert route("data/sql", {"host": "cloud.provisa.dev", "x-org-provisa": "acme"}) == main
    assert route("auth/me", {"host": "cloud.provisa.dev"}) == main


def test_with_no_sandbox_tier_everything_reaches_the_deployments_api(monkeypatch):
    import provisa.ui_server as ui_server

    monkeypatch.setattr(ui_server, "SANDBOX_API_URL", None)
    assert (
        ui_server.api_base_for("data/sql", {"host": "sbx0123456789ab.provisa.dev"})
        == ui_server.API_BASE_URL
    )


def test_a_demo_template_waits_for_its_source_tables_and_not_its_views(monkeypatch, tmp_path):
    """REQ-2006/REQ-2049: a view has no replica, so counting the weblogs demo's six views among
    what must land kept its template waiting forever (demo-bundles run 38588163850)."""
    from pathlib import Path

    from provisa.api.demo_templates import replicated_tables
    from provisa.core.config_loader import parse_config_dict, read_config_with_includes

    monkeypatch.setenv("PROVISA_NAMED_DEMO_DIR", str(tmp_path))
    weblogs = Path(__file__).resolve().parents[2] / "demo" / "named" / "weblogs" / "config.yaml"
    config = parse_config_dict(read_config_with_includes(weblogs))
    assert len(config.tables) == 12
    assert sorted(t.table_name for t in replicated_tables(config)) == [
        "customers",
        "order_items",
        "orders",
        "products",
        "shop_access",
        "shop_db_log",
    ]
