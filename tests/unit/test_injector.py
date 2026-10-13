# Copyright (c) 2026 Kenneth Stott
# Canary: 73455bd5-0963-4355-bb86-0b2aca759e81
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-940: the injector action — probe → token-gate → post the change event + fan out."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from provisa.events import queue
from provisa.events.injector import check_node


@asynccontextmanager
async def _conn(control_plane):
    async with control_plane.org().acquire() as conn:
        yield conn


def _probe(token: str | None = "tok"):
    """A transport that returns a fixed current token (str | None)."""

    async def p():
        return token

    return p


@pytest.mark.asyncio
async def test_unchanged_posts_nothing(control_plane):
    async with _conn(control_plane) as conn:
        # baseline token already persisted; the probe returns the same token → unchanged
        await queue.set_node_state(conn, "s.orders", probe_token="tok")
        eid = await check_node(
            conn,
            node="s.orders",
            change_signal="ttl",
            watermark_column=None,
            probe=_probe("tok"),
            dependents=["mv.daily"],
        )
        assert eid is None  # token-gated: no event, no wasted downstream work
        assert await queue.read_since(conn, cursor=0) == []


@pytest.mark.asyncio
async def test_an_unchanged_token_tells_whoever_keeps_the_copy(control_plane):
    """REQ-855: an unchanged token keeps the rows, and the copy is current as of the probe."""
    told: list[str] = []

    async def verified() -> None:
        told.append("verified")

    async with _conn(control_plane) as conn:
        await queue.set_node_state(conn, "s.orders", probe_token="tok")
        given = {
            "node": "s.orders",
            "change_signal": "probe",
            "watermark_column": None,
            "dependents": ["mv.daily"],
            "on_unchanged": verified,
        }
        assert await check_node(conn, probe=_probe("tok"), **given) is None
        assert told == ["verified"]
        # A changed token, and a probe that could not answer, verify nothing.
        assert await check_node(conn, probe=_probe("tok2"), **given) is not None
        assert await check_node(conn, probe=_probe(None), **given) is not None
        assert told == ["verified"]


@pytest.mark.asyncio
async def test_none_token_degrades_to_ttl_and_posts(control_plane):
    # a source with no token capability (None) is not gated — it re-posts every cadence (TTL degrade)
    async with _conn(control_plane) as conn:
        eid = await check_node(
            conn,
            node="s.orders",
            change_signal="ttl",
            watermark_column=None,
            probe=_probe(None),
            dependents=[],
        )
        assert eid is not None
        rows = await queue.read_since(conn, cursor=0)
        assert len(rows) == 1 and rows[0]["event_type"] == "replace"


@pytest.mark.asyncio
async def test_changed_poll_watermark_posts_append_and_fans_out(control_plane):
    async with _conn(control_plane) as conn:
        eid = await check_node(
            conn,
            node="s.orders",
            change_signal="ttl_probe",
            watermark_column="updated_at",
            probe=_probe("t2"),
            dependents=["mv.daily", "mv.by_cust"],
        )
        rows = await queue.read_since(conn, cursor=0)
        assert len(rows) == 1 and rows[0]["event_type"] == "append"  # poll+watermark → append
        assert rows[0]["payload"] == {"token": "t2"}
        # the new token is persisted as the baseline for the next comparison
        assert (await queue.get_node_state(conn, "s.orders"))["probe_token"] == "t2"
        # fanned out to both dependents (claimable)
        assert await queue.claim(
            conn, dependent_table="mv.daily", processor_name="A", now=datetime.now(timezone.utc)
        ) == [eid]


@pytest.mark.asyncio
async def test_probe_type_watermark_drives_append_shape(control_plane):
    # probe_type is the shape source of truth: watermark → append regardless of change_signal hints
    async with _conn(control_plane) as conn:
        await check_node(
            conn,
            node="s.wm",
            change_signal="probe",
            watermark_column=None,
            probe=_probe("v1"),
            dependents=[],
            probe_type="watermark",
        )
        rows = await queue.read_since(conn, cursor=0)
        assert rows[0]["event_type"] == "append"


@pytest.mark.asyncio
async def test_event_kind_from_change_signal(control_plane):
    async with _conn(control_plane) as conn:
        # ttl, no watermark → replace
        await check_node(
            conn,
            node="s.a",
            change_signal="ttl",
            watermark_column=None,
            probe=_probe("tok"),
            dependents=[],
        )
        # push (kafka) → delta (upsert by PK)
        await check_node(
            conn,
            node="s.b",
            change_signal="kafka",
            watermark_column=None,
            probe=_probe("tok"),
            dependents=[],
        )
        kinds = {r["source_table"]: r["event_type"] for r in await queue.read_since(conn, cursor=0)}
        assert kinds == {"s.a": "replace", "s.b": "delta"}


@pytest.mark.asyncio
async def test_a_probe_that_answers_only_unchanged_or_cannot_tell_asks_for_one_read_per_change(
    control_plane,
):
    """A Microsoft 365 mailbox has no token to compare: its probe follows the links its last
    completed read kept and answers the constant "unchanged", or None when something changed
    or it cannot tell (``microsoft365.loader.unchanged``). A completed read sets the node's
    baseline to that constant (the loader's ``settle``). Through the node's comparison: every
    None asks for a read and leaves the baseline alone; "unchanged" asks for nothing -- no
    read after the one just made, and no second read after a change."""
    from provisa.microsoft365.loader import UNCHANGED

    told: list[str] = []

    async def verified() -> None:
        told.append("verified")

    async with _conn(control_plane) as conn:
        given = {
            "node": "mail/default.messages",
            "change_signal": "ttl_probe",
            "watermark_column": None,
            "dependents": [],
            "on_unchanged": verified,
        }

        async def tick(answer: str | None) -> bool:
            """Whether the tick asked for a read."""
            return await check_node(conn, probe=_probe(answer), **given) is not None

        # Before any read has completed there are no links: it cannot tell, each time, and
        # nothing is kept from an answer that is not one.
        assert await tick(None) and await tick(None)
        assert await queue.get_node_state(conn, given["node"]) is None
        # The first read completes and settles the node.
        await queue.set_node_state(conn, given["node"], probe_token=UNCHANGED)
        assert not await tick(UNCHANGED) and told == ["verified"]  # not read again
        # A change: a read is asked for on every tick until one completes ...
        assert await tick(None) and await tick(None)
        state = await queue.get_node_state(conn, given["node"])
        assert state["probe_token"] == UNCHANGED  # ... and the baseline stood through it,
        assert not await tick(UNCHANGED)  # so the read that follows is not asked for twice.
        assert told == ["verified", "verified"]
