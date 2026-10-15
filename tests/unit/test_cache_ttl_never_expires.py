# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A cache_ttl of -1 never expires (REQ-2031); any other negative TTL is refused, and 0 keeps its
REQ-2003 meaning. Kept rows, fills and response-cache entries of a never-expiring table are kept
for good; its replica is never due again and never promoted; nothing listens for its changes."""

# Requirements: REQ-2031

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from provisa.core.cache_ttl import NEVER_EXPIRES, cache_ttl_refusal, expires_after
from provisa.core.models import Source, Table


@pytest.mark.parametrize("ttl", [None, -1, 0, 300])
def test_a_legal_ttl_is_accepted(ttl):
    assert cache_ttl_refusal(ttl) is None


def test_any_other_negative_ttl_is_refused():
    assert "never expires" in (cache_ttl_refusal(-2) or "")


def test_the_models_refuse_minus_two_and_take_minus_one():
    base = {"id": "s", "type": "postgresql", "host": "h", "port": 5432, "database": "d",
            "username": "u", "password": "p"}  # fmt: skip
    assert Source(**base, cache_ttl=-1).cache_ttl == NEVER_EXPIRES
    with pytest.raises(ValueError, match="cache_ttl must be -1"):
        Source(**base, cache_ttl=-2)
    table = {"source_id": "s", "domain_id": "d", "schema": "public", "table": "t", "columns": []}
    assert Table(**table, cache_ttl=-1).cache_ttl == NEVER_EXPIRES
    with pytest.raises(ValueError, match="cache_ttl must be -1"):
        Table(**table, cache_ttl=-5)


def test_something_kept_for_good_never_expires():
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert expires_after(now, NEVER_EXPIRES).year == 9999
    assert (expires_after(now, 60) - now).total_seconds() == 60


def _table(cache_ttl, role_ttl=None):
    return SimpleNamespace(cache_ttl=cache_ttl, role_ttl=role_ttl or {})


def test_no_reader_relaxes_a_ttl_that_never_expires():
    from provisa.federation.role_ttl import effective_ttl, max_accepted_ttl, never_expires

    src = SimpleNamespace(cache_ttl=None)
    table = _table(-1, {"analyst": 600})
    assert never_expires(table, src)
    assert effective_ttl(table, src, "analyst") == NEVER_EXPIRES
    assert max_accepted_ttl(table, src) == NEVER_EXPIRES


def test_a_kept_row_of_a_never_expiring_table_is_never_stale():
    from provisa.federation.query_residency import _row_stale

    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    assert _row_stale(long_ago, datetime.now(UTC), NEVER_EXPIRES, change_fed=False) is False
    assert _row_stale(long_ago, datetime.now(UTC), 60, change_fed=False) is True


def test_the_ttl_freshness_check_finds_it_fresh_however_old():
    from provisa.freshness.decision import Freshness
    from provisa.freshness.predicate import Ttl
    from provisa.freshness.adapters import StateSubject

    decision = Ttl(NEVER_EXPIRES).evaluate(StateSubject(refreshed_at=0.0), 10**9)
    assert decision.state is Freshness.FRESH


def test_a_response_reading_only_never_expiring_tables_is_kept_for_good():
    from provisa.cache.policy import CachePolicy, opt_in_ttl, resolve_policy

    assert resolve_policy(None, None, table_cache_ttl=-1) == (CachePolicy.TTL, NEVER_EXPIRES)
    assert opt_in_ttl(None, [NEVER_EXPIRES]) == NEVER_EXPIRES
    assert opt_in_ttl(None, [NEVER_EXPIRES, 120]) == 120
    assert opt_in_ttl(None, [NEVER_EXPIRES, 0]) == 0


def test_a_never_expiring_replica_is_read_only_from_itself():
    from provisa.federation.replica_routing import CACHE_TTL, live_while_building, table_floor

    src = SimpleNamespace(cache_ttl=-1, replicate=None, load_protected=False)
    reg = {"cache_ttl": None, "replicate": None, "load_protected": None}
    assert table_floor(src, reg, promoted=False) == CACHE_TTL
    import provisa.federation.replica_routing as routing

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(routing, "has_live_attach", lambda source, engine: True)
        assert live_while_building(src, reg, SimpleNamespace()) is False


def test_the_policy_says_it_never_expires():
    from provisa.federation.policy_summary import HotView, Serving, describe_refresh_policy

    src = Source(id="s", type="postgresql", host="h", port=5432, database="d", username="u",
                 password="p", cache_ttl=-1)  # fmt: skip
    table = Table(source_id="s", domain_id="d", schema="public", table="t", columns=[])
    summary = describe_refresh_policy(
        src, table, SimpleNamespace(), 300, hot=HotView(100, 60, 1000)
    )
    assert summary.serving is Serving.FROZEN and summary.text.startswith("Never expires")


def test_a_table_that_never_expires_has_no_event_node():
    from provisa.events.boot import build_source_node_spec

    src = SimpleNamespace(id="s", type=SimpleNamespace(value="postgresql"), cache_ttl=-1)
    tbl = SimpleNamespace(cache_ttl=None, schema_name="public", table_name="t", columns=[])
    spec = build_source_node_spec(
        tbl, src, engine=object(), engine_runtime=object(), source_fetch=lambda s, t: []
    )
    assert spec is None
