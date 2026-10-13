# Copyright (c) 2026 Kenneth Stott
# Canary: c4f19b2e-6a07-4d83-b5e1-0d92a7f3c518
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Polly bake-off: what a free-form question costs, per model, on the weblogs demo (REQ-2012).

Runs on manual dispatch only (.github/workflows/polly-bakeoff.yml), with a paid API key: it is
marked ``requires_polly_bakeoff`` and is in no other lane. Brings the weblogs demo up on an
isolated instance and asks Polly the same ten questions on each model in ``POLLY_BAKEOFF_MODELS``
(comma-separated), through ``POLLY_BAKEOFF_VIA`` -- ``openrouter`` (OPENROUTER_API_KEY; model ids
as OpenRouter names them) or ``anthropic`` (ANTHROPIC_API_KEY; Anthropic's ids).

Each question has a known answer, read from the demo with SQL on the same instance; an answer is
right when Polly's reply names it. Each question is its own conversation, so its usage is
everything that question cost: every call, tool round trips included. For each model the report
gives accuracy, the cost of a question (median and p90; OpenRouter's billed cost when it is the
gateway, else tokens at the price table's price), how many questions $0.25 buys at the median and
at the p90, the median latency and the share of input read from the prompt cache. It is written to
``POLLY_BAKEOFF_REPORT`` (JSON) and printed. The run fails only when a model cannot be asked at all.
"""

# Requirements: REQ-2012

from __future__ import annotations

import json
import os
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from tests.integration.polly_bakeoff_questions import QUESTIONS, Question
from tests.integration.test_weblogs_demo import (
    _DEMO,
    WeblogsStack,
    await_logs_landed,
    query,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_polly_bakeoff,
    # Out of every lane's default selection, as a live-credential test is (scripts/ci/run_lane.py).
    pytest.mark.requires_warehouse,
]

_ROLE = "org_admin"
_BUDGET_USD = 0.25


def _expected(server: Any, question: Question) -> list[str]:
    answers = [str(row["a"]) for row in query(server, question.answer_sql)]
    assert answers, f"no known answer for {question.text!r}"
    return answers


def _names(reply: str, answer: str) -> bool:
    """Whether ``reply`` names ``answer``: a number as a number (1,500 is 1500), a word as a word."""
    flat = reply.replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", answer):
        return re.search(rf"(?<![\d.]){re.escape(answer)}(?![\d])", flat) is not None
    return answer.lower() in reply.lower()


@dataclass
class Answer:
    question: str
    expected: list[str]
    reply: str = ""
    right: bool = False
    seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _ask(server: Any, question: str) -> tuple[str, dict[str, Any], str | None, float]:
    """One question as its own conversation: Polly's reply, the turn's usage, an error."""
    started = time.monotonic()
    text: list[str] = []
    usage: dict[str, Any] = {}
    error = None
    with httpx.stream(
        "POST",
        f"{server.base_url}/admin/mcp/chat",
        json={"messages": [{"role": "user", "content": question}]},
        headers={"X-Provisa-Role": _ROLE},
        timeout=300,
    ) as resp:
        assert resp.status_code == 200, resp.read()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event["type"] == "text":
                text.append(event["text"])
            elif event["type"] == "usage":
                usage = event
            elif event["type"] == "error":
                error = event["error"]
    return "".join(text), usage, error, time.monotonic() - started


def _cost(usage: dict[str, Any]) -> float | None:
    billed = usage.get("provider_cost_usd")
    return billed if billed is not None else usage.get("cost_usd")


def _summary(model: str, answers: list[Answer]) -> dict[str, Any]:
    costs = sorted(c for a in answers if (c := _cost(a.usage)) is not None)
    asked = [a for a in answers if a.error is None]
    cached = sum(a.usage.get("cache_read_tokens", 0) for a in asked)
    fresh = sum(
        a.usage.get("input_tokens", 0) + a.usage.get("cache_write_tokens", 0) for a in asked
    )
    median = statistics.median(costs) if costs else None
    p90 = costs[max(int(round(0.9 * len(costs))) - 1, 0)] if costs else None
    return {
        "model": model,
        "accuracy": f"{sum(a.right for a in answers)}/{len(answers)}",
        "errors": sum(a.error is not None for a in answers),
        "median_cost_usd": median,
        "p90_cost_usd": p90,
        "questions_per_budget_at_median": int(_BUDGET_USD // median) if median else None,
        "questions_per_budget_at_p90": int(_BUDGET_USD // p90) if p90 else None,
        "five_questions_at_p90_usd": round(5 * p90, 6) if p90 else None,
        "median_latency_s": round(statistics.median(a.seconds for a in answers), 2),
        "median_calls": statistics.median(a.usage.get("calls", 0) for a in asked) if asked else 0,
        "cached_input_share": round(cached / (cached + fresh), 3) if cached + fresh else None,
        "answers": [a.__dict__ for a in answers],
    }


def _config(tmp: Path, via: str, first_model: str) -> Path:
    """The demo's own config, with Polly pointed at the gateway the run uses."""
    cfg: dict[str, Any] = yaml.safe_load((_DEMO / "config.yaml").read_text())
    if via == "openrouter":
        cfg["ai_endpoints"] = [
            {
                "id": "openrouter",
                "style": "openai",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
            }
        ]
        cfg["ai_models"] = {"mcp_chat": {"vendor": "openrouter", "model": first_model}}
    else:
        cfg["ai_models"] = {"mcp_chat": {"vendor": "anthropic", "model": first_model}}
    path = tmp / "bakeoff.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _use_model(server: Any, model: str) -> None:
    resp = httpx.put(
        f"{server.base_url}/admin/settings/catalog",
        json={"values": {"mcp.chat_model": model}},
        headers={"X-Provisa-Role": _ROLE},
        timeout=60,
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture(scope="module")
def run():
    models = [m.strip() for m in os.environ["POLLY_BAKEOFF_MODELS"].split(",") if m.strip()]
    via = os.environ["POLLY_BAKEOFF_VIA"]
    assert via in ("openrouter", "anthropic"), f"POLLY_BAKEOFF_VIA is {via!r}"
    key = "OPENROUTER_API_KEY" if via == "openrouter" else "ANTHROPIC_API_KEY"
    assert os.environ.get(key), f"{key} is not set"
    return via, models


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    demo = WeblogsStack(tmp_path_factory.mktemp("weblogs"))
    try:
        demo.up()
        yield demo
    finally:
        demo.down()


@pytest.fixture(scope="module")
def server(stack, run, tmp_path_factory):
    from tests.integration.isolated_server import IsolatedServer

    via, models = run
    srv = IsolatedServer(
        "polly_bakeoff",
        engine="duckdb",
        config=str(_config(tmp_path_factory.mktemp("bakeoff"), via, models[0])),
        control_plane="sqlite",
        env={
            **stack.env,
            "PROVISA_LOGS_ALLOWED_ROOTS": str(stack.home / "logs"),
            "PROVISA_DATA_DIR": str(stack.home / "provisa"),
        },
    )
    srv.start(timeout=300)
    try:
        await_logs_landed(srv)
        yield srv
    except BaseException:
        print(srv.dump_stderr_debug()[-6000:])
        raise
    finally:
        srv.stop_process()


def test_polly_bakeoff(server, run):
    via, models = run
    expected = {q.text: _expected(server, q) for q in QUESTIONS}
    report = {"via": via, "budget_usd": _BUDGET_USD, "questions": len(QUESTIONS), "models": []}
    for model in models:
        _use_model(server, model)
        answers = []
        for question in QUESTIONS:
            reply, usage, error, seconds = _ask(server, question.text)
            want = expected[question.text]
            answers.append(
                Answer(
                    question=question.text,
                    expected=want,
                    reply=reply,
                    right=error is None and any(_names(reply, w) for w in want),
                    seconds=seconds,
                    usage=usage,
                    error=error,
                )
            )
        report["models"].append(_summary(model, answers))

    out = Path(os.environ.get("POLLY_BAKEOFF_REPORT", "polly-bakeoff.json"))
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nPolly bake-off via {via}, {len(QUESTIONS)} questions, budget ${_BUDGET_USD}:")
    for m in report["models"]:
        print(
            f"  {m['model']}: right {m['accuracy']}, errors {m['errors']}, "
            f"median ${m['median_cost_usd']}, p90 ${m['p90_cost_usd']}, "
            f"{m['questions_per_budget_at_median']} / {m['questions_per_budget_at_p90']} "
            f"questions per ${_BUDGET_USD} (median / p90), latency {m['median_latency_s']} s, "
            f"cached input {m['cached_input_share']}"
        )
    unasked = [m["model"] for m in report["models"] if m["errors"] == len(QUESTIONS)]
    assert not unasked, f"these models could not be asked at all: {unasked} (see {out})"
