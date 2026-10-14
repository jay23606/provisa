# Copyright (c) 2026 Kenneth Stott
# Canary: 5f1c8e27-3a96-4d0b-b7e4-9c2a6d81f053
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Polly's chat on a Google model, through Vertex AI's own ``generateContent`` (REQ-1797).

aisuite's Google provider builds its generation config from the temperature alone, so a cap on
what a call may generate never reaches Google, and it needs the Vertex SDK, which Provisa does not
install. This client speaks Vertex's REST API directly, with the service account the readiness
check already requires (GOOGLE_PROJECT_ID, GOOGLE_REGION, GOOGLE_APPLICATION_CREDENTIALS), and
answers in the OpenAI shape the chat loop reads from every aisuite provider: the call's
OpenAI-shaped messages and tools go in, and a response with ``choices[0].message`` (content,
tool_calls), ``finish_reason`` and ``usage`` comes out. ``max_output_tokens`` is sent as
``generationConfig.maxOutputTokens``."""

# Requirements: REQ-1797, REQ-1838

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from typing import Any

import httpx

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# The keys of a tool's JSON schema Vertex's function declarations read (an OpenAPI subset).
_SCHEMA_KEYS = ("type", "description", "enum", "required")


def _schema(schema: dict) -> dict:
    """A tool parameter's JSON schema as Vertex declares it: the keys it reads, nested."""
    out = {k: schema[k] for k in _SCHEMA_KEYS if k in schema}
    if "properties" in schema:
        out["properties"] = {name: _schema(s) for name, s in schema["properties"].items()}
    if "items" in schema:
        out["items"] = _schema(schema["items"])
    return out


def _declaration(tool: dict) -> dict:
    fn = tool["function"]
    declaration = {"name": fn["name"], "description": fn.get("description", "")}
    params = fn.get("parameters") or {}
    if params.get("properties"):  # a tool with no parameters declares none
        declaration["parameters"] = _schema(params)
    return declaration


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block.get("type") == "text")


def _response(content: str) -> dict:
    """A tool's result as a functionResponse's ``response``, which Vertex takes as an object."""
    try:
        value = json.loads(content)
    except ValueError:
        return {"content": content}
    return value if isinstance(value, dict) else {"content": value}


def request_body(messages: list[dict], tools: list[dict], max_output_tokens: int) -> dict:
    """The generateContent request for an OpenAI-shaped conversation and tool list."""
    system: list[str] = []
    contents: list[dict] = []
    names: dict[str, str] = {}  # tool call id -> the function it called
    for m in messages:
        role = m["role"]
        if role == "system":
            system.append(_text(m["content"]))
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": _text(m["content"])}]})
        elif role == "assistant":
            parts: list[dict] = []
            if m.get("content"):
                parts.append({"text": _text(m["content"])})
            for call in m.get("tool_calls") or []:
                names[call["id"]] = call["function"]["name"]
                parts.append(
                    {
                        "functionCall": {
                            "name": call["function"]["name"],
                            "args": json.loads(call["function"]["arguments"] or "{}"),
                        }
                    }
                )
            if parts:  # an assistant turn that said nothing and called nothing has no Vertex form
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            part = {
                "functionResponse": {
                    "name": names[m["tool_call_id"]],
                    "response": _response(m["content"]),
                }
            }
            # The responses to one turn's calls go back together, as one user turn.
            previous = contents[-1] if contents else None
            if (
                previous
                and previous["role"] == "user"
                and "functionResponse" in previous["parts"][0]
            ):
                previous["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        else:
            raise ValueError(f"a chat message has no Vertex form for role {role!r}")
    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_output_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if tools:
        body["tools"] = [{"functionDeclarations": [_declaration(t) for t in tools]}]
    return body


def openai_response(answer: dict) -> Any:
    """A generateContent answer in the OpenAI shape the chat loop reads."""
    candidate = answer["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p["text"] for p in parts if "text" in p)
    calls = [
        SimpleNamespace(
            id=f"call_{uuid.uuid4().hex}",
            type="function",
            function=SimpleNamespace(
                name=p["functionCall"]["name"],
                arguments=json.dumps(p["functionCall"].get("args", {})),
            ),
        )
        for p in parts
        if "functionCall" in p
    ]
    finish = (
        "tool_calls" if calls else {"MAX_TOKENS": "length"}.get(candidate["finishReason"], "stop")
    )
    meta = answer["usageMetadata"]
    usage = SimpleNamespace(
        prompt_tokens=meta["promptTokenCount"],
        completion_tokens=meta.get("candidatesTokenCount", 0),
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=meta.get("cachedContentTokenCount", 0), cache_write_tokens=0
        ),
    )
    message = SimpleNamespace(content=text or None, tool_calls=calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=usage
    )


class VertexChat:
    """Chat completions on a Google model through Vertex AI, as the chat loop calls a provider."""

    def __init__(self, project: str, region: str, credentials_path: str) -> None:
        from google.oauth2 import service_account

        self._project = project
        self._region = region
        self._credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=[_SCOPE]
        )

    @classmethod
    def from_env(cls) -> VertexChat:
        """The client the readiness check's three settings name."""
        return cls(
            os.environ["GOOGLE_PROJECT_ID"],
            os.environ["GOOGLE_REGION"],
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        )

    def _url(self, model: str) -> str:
        host = (
            "aiplatform.googleapis.com"
            if self._region == "global"
            else f"{self._region}-aiplatform.googleapis.com"
        )
        return (
            f"https://{host}/v1/projects/{self._project}/locations/{self._region}"
            f"/publishers/google/models/{model}:generateContent"
        )

    def _token(self) -> str:
        from google.auth.transport.requests import Request

        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    def chat_completions_create(
        self, model: str, messages: list[dict], *, tools: list[dict], max_output_tokens: int
    ) -> Any:
        resp = httpx.post(
            self._url(model),
            json=request_body(messages, tools, max_output_tokens),
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=300,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Vertex AI answered {resp.status_code}: {resp.text}")
        return openai_response(resp.json())
