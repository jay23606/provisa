# Copyright (c) 2026 Kenneth Stott
# Canary: 0f6c3b84-5d29-4e71-a8b3-9e2d7c1f4a65
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Cypher statement Polly would put on the Graph page is checked first (REQ-1795, REQ-1848).
One that does not run never reaches the browser: the chat answers that navigate with the real
error, the model corrects the statement, and the corrected navigate is the one the browser runs.
A navigate that sets only the Graph page's view carries no statement and goes through as it is.
"""

# Requirements: REQ-1795, REQ-1848

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provisa.api.mcp import chat as chat_mod
from provisa.api.mcp import cypher_check
from tests.unit.test_mcp_chat import (  # the chat's fakes, and the key its vendor is configured with
    _block,
    _install_fake_anthropic,
    _state,
    _a_configured_vendor_key,  # noqa: F401  (autouse fixture: the readiness check needs a key)
)

pytestmark = pytest.mark.asyncio

_BAD = "MATCH (o:Shop:Orders), (c:Shop:Customers) RETURN o, c"
_GOOD = "MATCH (o:Shop:Orders)-[r:PLACED_BY]->(c:Shop:Customers) RETURN o, r, c LIMIT 25"


def _navigate(call_id: str, state: dict):
    return SimpleNamespace(
        content=[
            _block(
                type="tool_use",
                name="navigate",
                id=call_id,
                input={"route": "/graph", "state": state},
            )
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


@pytest.fixture(autouse=True)
def _checks(monkeypatch):
    monkeypatch.setenv("PROVISA_MCP_CHAT_MODEL", "claude-haiku-5-5")
    checked: list[str] = []

    async def _check(_state, _role, query):
        checked.append(query)
        if query == _BAD:
            return cypher_check.GraphRead("Unexpected token ',' at pos 21", {})
        return cypher_check.GraphRead(None, {"o": "node", "c": "node", "r": "edge"})

    monkeypatch.setattr(cypher_check, "check_graph_read", _check)
    return checked


async def test_a_statement_that_does_not_run_never_reaches_the_page(monkeypatch, _checks):
    holder = _install_fake_anthropic(
        monkeypatch,
        [
            _navigate("t1", {"query": _BAD, "autoRun": True}),
            _navigate("t2", {"query": _GOOD, "autoRun": True}),
        ],
    )
    convo = [{"role": "user", "content": "draw a few orders and their customers"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]

    # The first statement went back to the model, with the error, not to the browser.
    second_call = holder["client"].messages.calls[1]
    refused = second_call["messages"][-1]["content"][0]
    assert refused["tool_use_id"] == "t1" and refused["is_error"] is True
    assert "Unexpected token ','" in refused["content"]
    # The corrected one is what the browser is asked to run.
    paused = next(e for e in events if e["type"] == "awaiting_client_tools")
    assert [c["input"]["state"]["query"] for c in paused["pending"]] == [_GOOD]
    assert _checks == [_BAD, _GOOD]


async def test_a_navigate_that_sets_only_the_view_goes_through_unchecked(monkeypatch, _checks):
    _install_fake_anthropic(monkeypatch, [_navigate("t1", {"view": {"groupBy": "region"}})])
    convo = [{"role": "user", "content": "group by region"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]
    paused = next(e for e in events if e["type"] == "awaiting_client_tools")
    assert paused["pending"][0]["input"]["state"] == {"view": {"groupBy": "region"}}
    assert _checks == []
    # Its result can confirm only the request: the page does not report back what it drew.
    assert paused["pending"][0]["confirmation"] == (
        'The Graph page was asked to set its view to {"groupBy": "region"} on the graph already '
        "on screen; the page does not report back what it drew."
    )


async def test_a_navigate_that_reaches_the_page_carries_what_its_result_can_confirm(
    monkeypatch, _checks
):
    """ "I've opened the Graph page with the analysis rendered" was said with nothing to say so:
    the browser reports only that it navigated, so the result carries what the page was handed."""
    _install_fake_anthropic(monkeypatch, [_navigate("t1", {"query": _GOOD, "autoRun": True})])
    convo = [{"role": "user", "content": "show this in a network graph"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]
    paused = next(e for e in events if e["type"] == "awaiting_client_tools")
    assert paused["pending"][0]["confirmation"] == (
        "The Graph page was handed the statement, which checks clean and returns node column(s) "
        "o, c; edge column(s) r. The page runs it; it does not report back the rows it drew."
    )


async def test_a_navigate_off_the_graph_page_carries_no_confirmation(monkeypatch, _checks):
    _install_fake_anthropic(
        monkeypatch,
        [
            SimpleNamespace(
                content=[
                    _block(
                        type="tool_use",
                        name="navigate",
                        id="t1",
                        input={"route": "/sql", "state": {"sql": "SELECT 1", "autoRun": True}},
                    )
                ],
                stop_reason="tool_use",
            )
        ],
    )
    convo = [{"role": "user", "content": "show it on the SQL page"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]
    paused = next(e for e in events if e["type"] == "awaiting_client_tools")
    assert "confirmation" not in paused["pending"][0]
    assert _checks == []
