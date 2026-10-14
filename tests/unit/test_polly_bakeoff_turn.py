# Copyright (c) 2026 Kenneth Stott
# Canary: 0d9f4a26-7b18-4c53-9e2a-5f81c3b6d740
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A bake-off question is asked as the chat panel asks it (REQ-2012): a navigate pause is answered
as the browser answers it and the turn resumes. GPT-5.4 mini's demo answer ended in a navigate,
and graded as an empty reply (run 38625083413)."""

from __future__ import annotations

import json

from tests.integration.polly_bakeoff_turn import ask

_NAVIGATE = {
    "id": "c1",
    "name": "navigate",
    "input": {"route": "/sql", "state": {"sql": "SELECT path FROM view_slowest_pages"}},
    "confirmation": None,
}


def _usage(calls: int, cost: float | None) -> dict:
    return {"type": "usage", "model": "m", "calls": calls, "input_tokens": 10, "cost_usd": cost}


def test_a_navigate_is_answered_as_the_browser_answers_it_and_the_turn_resumes():
    posted: list[list[dict]] = []
    first = [
        {"type": "tool_use", "name": "navigate", "input": _NAVIGATE["input"], "client": True},
        {
            "type": "awaiting_client_tools",
            "assistant_content": [{"type": "tool_use", "id": "c1", "name": "navigate"}],
            "server_tool_results": [{"type": "tool_result", "tool_use_id": "s1", "content": "[]"}],
            "pending": [{**_NAVIGATE, "confirmation": "The page runs it."}],
            "prior_messages": [{"role": "assistant", "content": [{"type": "text", "text": "p"}]}],
        },
        _usage(2, 0.01),
        {"type": "done"},
    ]
    second = [
        {"type": "text", "text": "/reports/top is the slowest page."},
        _usage(1, 0.002),
        {"type": "done"},
    ]

    def stream(convo):
        posted.append(convo)
        return iter([first, second][len(posted) - 1])

    turn = ask(stream, "Which pages are slowest?")

    assert turn.reply == "/reports/top is the slowest page." and turn.error is None
    resumed = posted[1]
    assert resumed[0] == {"role": "user", "content": "Which pages are slowest?"}
    assert resumed[1] == {"role": "assistant", "content": [{"type": "text", "text": "p"}]}
    assert resumed[2]["role"] == "assistant"
    answer = resumed[3]["content"]
    assert answer[0]["tool_use_id"] == "s1"
    assert answer[1]["tool_use_id"] == "c1" and answer[1]["is_error"] is False
    assert json.loads(answer[1]["content"]) == {
        "success": True,
        "message": "Navigated to /sql. The page runs it.",
    }
    assert turn.usage["calls"] == 3 and abs(turn.usage["cost_usd"] - 0.012) < 1e-9
    assert turn.tools == [{"name": "navigate", "input": _NAVIGATE["input"], "is_error": False}]


def test_a_choice_no_one_can_make_ends_the_question_with_that_error():
    pause = {
        "type": "awaiting_client_tools",
        "assistant_content": [],
        "server_tool_results": [],
        "pending": [{"id": "c1", "name": "present_choice", "input": {"question": "Which?"}}],
        "prior_messages": [],
    }
    events = [
        {"type": "tool_use", "name": "present_choice", "input": {"question": "Which?"}},
        pause,
        _usage(1, None),
        {"type": "done"},
    ]
    turn = ask(lambda convo: iter(events), "q")
    assert turn.error == "asked a person through present_choice; no one answers in the bake-off"
    assert turn.usage["cost_usd"] is None
