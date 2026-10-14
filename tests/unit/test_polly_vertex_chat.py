# Copyright (c) 2026 Kenneth Stott
# Canary: 8a4d2f69-1c75-4e3b-9d08-6b7e5c2a1f94
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Polly on a Google model talks to Vertex AI directly (REQ-1797, REQ-1838): every call carries
the chat's output cap as generationConfig.maxOutputTokens, and a tool call goes out as a
functionCall and comes back as a functionResponse, as on every other vendor."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml

from provisa.api.mcp import chat as chat_mod
from provisa.api.mcp import tools as mcp_tools
from provisa.api.mcp import vertex_chat
from tests.unit.test_mcp_chat import (  # the chat's fakes, and the key its vendor is configured with
    _async_result,
    _state,
    _a_configured_vendor_key,  # noqa: F401  (autouse fixture)
)


class _Credentials:
    valid = True
    token = "vertex-token"


def _answer(parts: list[dict], finish: str = "STOP") -> dict:
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 8},
    }


@pytest.fixture
def vertex(monkeypatch, tmp_path):
    """Polly configured for a Gemini model, with Vertex AI's endpoint answered here."""
    import os

    cfg = tmp_path / "provisa.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {"sources": [], "ai_models": {"mcp_chat": {"vendor": "google", "model": "gemini-x"}}}
        )
    )
    monkeypatch.setitem(os.environ, "PROVISA_CONFIG", str(cfg))
    monkeypatch.setenv("GOOGLE_PROJECT_ID", "acme-ai")
    monkeypatch.setenv("GOOGLE_REGION", "us-central1")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "sa.json"))
    from google.oauth2 import service_account

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        classmethod(lambda cls, path, scopes: _Credentials()),
    )
    answers = [
        _answer([{"functionCall": {"name": "list_schemas", "args": {}}}]),
        _answer([{"text": "There is one schema: sales."}]),
    ]
    sent: list[dict] = []

    def _post(url, *, json, headers, timeout):
        sent.append({"url": url, "body": json, "headers": headers})
        return SimpleNamespace(status_code=200, json=lambda: answers.pop(0), text="")

    monkeypatch.setattr(vertex_chat.httpx, "post", _post)
    monkeypatch.setattr(mcp_tools, "list_schemas", lambda *_a, **_k: _async_result(["sales"]))
    return sent


@pytest.mark.asyncio
async def test_a_google_call_is_capped_and_its_tool_call_round_trips(vertex):
    convo = [{"role": "user", "content": "what schemas are there?"}]
    events = [ev async for ev in chat_mod.run_chat(_state(), "analyst", convo)]

    first, second = vertex
    assert first["url"] == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/acme-ai/locations/"
        "us-central1/publishers/google/models/gemini-x:generateContent"
    )
    assert first["headers"]["Authorization"] == "Bearer vertex-token"
    assert first["body"]["generationConfig"] == {"maxOutputTokens": chat_mod._MAX_TOKENS}
    declared = {d["name"] for d in first["body"]["tools"][0]["functionDeclarations"]}
    assert "list_schemas" in declared and "navigate" in declared
    assert "Polly" in first["body"]["systemInstruction"]["parts"][0]["text"]

    # The model's call, and the tool's result, go back on the next call.
    assert second["body"]["generationConfig"] == {"maxOutputTokens": chat_mod._MAX_TOKENS}
    call, result = second["body"]["contents"][-2:]
    assert call == {
        "role": "model",
        "parts": [{"functionCall": {"name": "list_schemas", "args": {}}}],
    }
    assert result == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "list_schemas", "response": {"content": ["sales"]}}}
        ],
    }
    assert [e["type"] for e in events] == ["tool_use", "tool_result", "text", "usage", "done"]
    assert events[2]["text"] == "There is one schema: sales."


def test_one_turns_calls_answer_together_and_schemas_keep_what_vertex_reads():
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "function": {"name": "one", "arguments": "{}"}},
                {"id": "b", "function": {"name": "two", "arguments": '{"x": 1}'}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": json.dumps({"ok": True})},
        {"role": "tool", "tool_call_id": "b", "content": "not json"},
        {"role": "assistant", "content": ""},  # said nothing, called nothing
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "one", "parameters": {"type": "object", "properties": {}}},
        },
        {
            "type": "function",
            "function": {
                "name": "two",
                "description": "Two.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "runs": {"type": "object", "additionalProperties": {"type": "string"}},
                        "tags": {"type": "array", "items": {"type": "string", "default": "a"}},
                    },
                    "required": ["x"],
                },
            },
        },
    ]
    body = vertex_chat.request_body(messages, tools, 32000)
    assert body["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert body["contents"][-1] == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "one", "response": {"ok": True}}},
            {"functionResponse": {"name": "two", "response": {"content": "not json"}}},
        ],
    }
    one, two = body["tools"][0]["functionDeclarations"]
    assert one == {"name": "one", "description": ""}
    assert two["parameters"] == {
        "type": "object",
        "required": ["x"],
        "properties": {
            "x": {"type": "integer"},
            "runs": {"type": "object"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }


def test_an_answer_cut_off_at_the_cap_says_so():
    resp = vertex_chat.openai_response(_answer([{"text": "partial"}], finish="MAX_TOKENS"))
    assert resp.choices[0].finish_reason == "length"
    assert resp.usage.prompt_tokens == 120 and resp.usage.completion_tokens == 8
