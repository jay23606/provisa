# Copyright (c) 2026 Kenneth Stott
# Canary: 6c2e8b41-9f37-4a05-b8d1-2e7a5c9f0d63
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""One bake-off question as the chat panel asks it (REQ-2012): the turn, every client-tool pause
answered the way the browser answers it and the turn resumed, as useMcpChat.ts does.

A pause the browser would answer with a person's choice (present_choice) or confirmation
(refresh_mv) has no one to answer it here: the question ends with that as its error. Kept apart
from the e2e test so it can be checked without a server."""

# Requirements: REQ-2012, REQ-1795

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

#: How many client-tool pauses one question may resume: the chat bounds each request's rounds,
#: and this bounds the requests.
RESUMES = 8


@dataclass
class Turn:
    reply: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # Each tool the model called, its input, and whether it failed.
    tools: list[dict[str, Any]] = field(default_factory=list)


def client_result(call: dict[str, Any]) -> dict[str, Any] | None:
    """What the browser answers a client tool with (clientTools.ts, plus the server's confirmation
    as useMcpChat.ts adds it), or None when a person would have to answer it."""
    if call["name"] != "navigate":
        return None
    message = f"Navigated to {call['input']['route']}"
    if call.get("confirmation"):
        message = f"{message}. {call['confirmation']}"
    return {"success": True, "message": message}


def add_usage(total: dict[str, Any], more: dict[str, Any]) -> dict[str, Any]:
    """Two requests' usage events as one: their counts and costs summed. A cost one of them does
    not report is not known for the two."""
    if not total:
        return dict(more)
    summed = dict(more)
    for key, value in more.items():
        if key in ("type", "model"):
            continue
        before = total.get(key)
        summed[key] = None if value is None or before is None else before + value
    return summed


def ask(stream: Callable[[list[dict[str, Any]]], Iterable[dict[str, Any]]], question: str) -> Turn:
    """``question`` as one conversation. ``stream`` posts a conversation to the chat and yields
    its events."""
    turn = Turn()
    text: list[str] = []
    convo: list[dict[str, Any]] = [{"role": "user", "content": question}]
    for _ in range(RESUMES + 1):
        paused = None
        for event in stream(convo):
            kind = event["type"]
            if kind == "text":
                text.append(event["text"])
            elif kind == "tool_use":
                turn.tools.append(
                    {"name": event["name"], "input": event["input"], "is_error": None}
                )
            elif kind == "tool_result":
                called = next(t for t in reversed(turn.tools) if t["name"] == event["name"])
                called["is_error"] = event["is_error"]
            elif kind == "usage":
                turn.usage = add_usage(turn.usage, event)
            elif kind == "error":
                turn.error = event["error"]
            elif kind == "awaiting_client_tools":
                paused = event
        if paused is None:
            break
        results = []
        for call in paused["pending"]:
            answered = client_result(call)
            if answered is None:
                turn.error = (
                    f"asked a person through {call['name']}; no one answers in the bake-off"
                )
                turn.reply = "".join(text)
                return turn
            next(t for t in reversed(turn.tools) if t["name"] == call["name"])["is_error"] = False
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(answered),
                    "is_error": False,
                }
            )
        convo = [
            *convo,
            *paused["prior_messages"],
            {"role": "assistant", "content": paused["assistant_content"]},
            {"role": "user", "content": [*paused["server_tool_results"], *results]},
        ]
    else:
        turn.error = f"still pausing for the browser after {RESUMES} resumes"
    turn.reply = "".join(text)
    return turn
