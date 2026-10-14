# Copyright (c) 2026 Kenneth Stott
# Canary: 5e9a1c37-28d4-4b6f-9a03-c7d1e4f2b860
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a Polly turn uses and costs, and the prompt cache that makes it cheaper (REQ-2012).

Every call marks the repeated prefix -- the tool definitions, the system prompt, and the
conversation so far -- for the prompt cache, so a tool round trip or the next question reads it
instead of paying for it again. A turn ends with a ``usage`` event: its tokens summed over every
call, and its cost at the model's price in the operator's price table (and what OpenRouter
billed, when it is the gateway).
"""

# Requirements: REQ-2012

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from provisa.api.mcp import chat as chat_mod
from provisa.api.mcp import polly_usage
from provisa.api.mcp.polly_usage import Price, PriceTableError, Usage
from tests.unit.test_mcp_chat import (  # the chat's fakes, and the key its vendor is configured with
    _block,
    _install_fake_aisuite,
    _install_fake_anthropic,
    _state,
    _a_configured_vendor_key,  # noqa: F401  (autouse fixture: the readiness check needs a key)
)


def test_the_price_table_reads_each_entry_and_refuses_one_that_does_not():
    table = polly_usage.parse_prices(["claude-haiku-5-5 0.1 0.5 0.01 0.125"])
    assert table == {"claude-haiku-5-5": Price(0.1, 0.5, 0.01, 0.125)}
    with pytest.raises(PriceTableError, match="'claude-haiku-5-5 0.1 0.5'"):
        polly_usage.parse_prices(["claude-haiku-5-5 0.1 0.5"])
    with pytest.raises(PriceTableError, match="cheap"):
        polly_usage.parse_prices(["m cheap 1 1 1"])


def test_cost_is_each_kind_of_token_at_its_price():
    usage = Usage(
        input_tokens=1_000, output_tokens=2_000, cache_read_tokens=100_000, cache_write_tokens=0
    )
    # 1k fresh at 0.1 + 2k out at 0.5 + 100k cached at 0.01 per million
    assert polly_usage.cost_usd(usage, Price(0.1, 0.5, 0.01, 0.125)) == pytest.approx(0.0021)


def test_openai_usage_counts_cached_input_apart_from_fresh():
    usage = polly_usage.from_openai(
        SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=300,
            prompt_tokens_details=SimpleNamespace(cached_tokens=8_000, cache_write_tokens=500),
        )
    )
    assert usage == Usage(1_500, 300, 8_000, 500, 1)


def test_a_model_with_no_price_reports_tokens_and_no_cost():
    event = polly_usage.usage_event("some-unlisted-model", Usage(10, 5, calls=1))
    assert (event["input_tokens"], event["output_tokens"], event["cost_usd"]) == (10, 5, None)


def _anthropic_usage(fresh, out, read, written):
    return SimpleNamespace(
        input_tokens=fresh,
        output_tokens=out,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=written,
    )


@pytest.mark.asyncio
async def test_every_anthropic_call_caches_its_prefix_and_the_turn_reports_its_usage(monkeypatch):
    from provisa.api.mcp import tools as mcp_tools

    monkeypatch.setenv("PROVISA_MCP_CHAT_MODEL", "claude-haiku-5-5")
    first = SimpleNamespace(
        content=[_block(type="tool_use", name="search_catalog", input={"query": "x"}, id="t1")],
        stop_reason="tool_use",
        usage=_anthropic_usage(200, 40, 0, 9_000),
    )
    second = SimpleNamespace(
        content=[_block(type="text", text="done")],
        stop_reason="end_turn",
        usage=_anthropic_usage(150, 60, 9_000, 0),
    )
    holder = _install_fake_anthropic(monkeypatch, [first, second])

    async def _search(_state, _role, _query, k=5):
        return []

    monkeypatch.setattr(mcp_tools, "search_catalog", _search)
    convo = [{"role": "user", "content": "where is revenue?"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]

    calls = holder["client"].messages.calls
    for call in calls:
        assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
        assert call["tools"][-1]["cache_control"] == {"type": "ephemeral"}
        assert not any("cache_control" in t for t in call["tools"][:-1])
        assert call["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # The round trip's request reads the first call's prefix: its last block is the tool result.
    assert calls[1]["messages"][-1]["content"][-1]["type"] == "tool_result"
    # The conversation sent back to the browser carries no cache marks.
    assert convo[0] == {"role": "user", "content": "where is revenue?"}

    usage = next(e for e in events if e["type"] == "usage")
    assert [e["type"] for e in events][-2:] == ["usage", "done"]
    assert (
        usage["calls"],
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_read_tokens"],
        usage["cache_write_tokens"],
    ) == (2, 350, 100, 9_000, 9_000)
    # At the default price of claude-haiku-5-5: 0.1 / 0.5 / 0.01 / 0.125 per million.
    assert usage["cost_usd"] == pytest.approx(
        (350 * 0.1 + 100 * 0.5 + 9_000 * 0.01 + 9_000 * 0.125) / 1_000_000
    )


@pytest.mark.asyncio
async def test_an_anthropic_model_through_openrouter_caches_and_reports_what_was_billed(
    tmp_path, monkeypatch
):
    config = {
        "sources": [],
        "ai_endpoints": [
            {
                "id": "openrouter",
                "style": "openai",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
            }
        ],
        "ai_models": {"mcp_chat": {"vendor": "openrouter", "model": "anthropic/claude-haiku-5.5"}},
    }
    (tmp_path / "provisa.yaml").write_text(yaml.dump(config))
    monkeypatch.setenv("PROVISA_CONFIG", str(tmp_path / "provisa.yaml"))
    monkeypatch.delenv("PROVISA_MCP_CHAT_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hi", tool_calls=None), finish_reason="stop"
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=9_100,
            completion_tokens=20,
            prompt_tokens_details=SimpleNamespace(cached_tokens=9_000, cache_write_tokens=0),
            cost=0.00012,
        ),
    )
    holder = _install_fake_aisuite(monkeypatch, [response])

    events = [
        ev
        async for ev in chat_mod.run_chat(_state(), "analyst", [{"role": "user", "content": "hi"}])
    ]

    call = holder["provider"].calls[0]
    assert call["model"] == "anthropic/claude-haiku-5.5"
    system = call["messages"][0]
    assert system["role"] == "system"
    assert system["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert call["extra_body"] == {"usage": {"include": True}}
    usage = next(e for e in events if e["type"] == "usage")
    assert (usage["input_tokens"], usage["cache_read_tokens"], usage["output_tokens"]) == (
        100,
        9_000,
        20,
    )
    assert usage["provider_cost_usd"] == pytest.approx(0.00012)
    assert usage["cost_usd"] == pytest.approx((100 * 0.1 + 20 * 0.5 + 9_000 * 0.01) / 1_000_000)


def test_an_unreadable_price_table_is_refused_when_it_is_saved():
    from provisa.api.admin import settings_guards

    settings_guards.check({"polly.model_prices": ["claude-haiku-5-5 0.1 0.5 0.01 0.125"]})
    with pytest.raises(settings_guards.Refused) as refused:
        settings_guards.check({"polly.model_prices": ["claude-haiku-5-5 cheap"]})
    assert (refused.value.field, refused.value.reason, refused.value.params) == (
        "polly.model_prices",
        "price_entry_invalid",
        {"entry": "claude-haiku-5-5 cheap"},
    )


def test_the_price_table_is_offered_as_a_table_of_its_columns():
    from provisa.core import settings_registry

    described = settings_registry.describe("polly.model_prices")
    assert described["type"] == "list"
    assert described["columns"] == ["model", "input", "output", "cache_read", "cache_write"]
    assert "claude-haiku-5-5 0.1 0.5 0.01 0.125" in described["default"]
