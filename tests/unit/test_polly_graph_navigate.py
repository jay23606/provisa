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
from tests.unit.test_mcp_chat import _block, _install_fake_anthropic, _state

pytestmark = pytest.mark.asyncio

_BAD = "MATCH (o:Shop:Orders), (c:Shop:Customers) RETURN o, c"
_GOOD = "MATCH (o:Shop:Orders)-[:PLACED_BY]->(c:Shop:Customers) RETURN o, c LIMIT 25"


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

    async def _problem(_state, _role, query):
        checked.append(query)
        return "Unexpected token ',' at pos 21" if query == _BAD else None

    monkeypatch.setattr(cypher_check, "cypher_read_problem", _problem)
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
