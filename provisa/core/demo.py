# Copyright (c) 2026 Kenneth Stott
# Canary: 1cbbf391-7348-4ad8-869a-6d3a78c79fa9
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Demo-mode signal (REQ-1220). PROVISA_DEMO is exported by every demo launch path:
``provisa run --demo``, scripts/provisa, packaging first-launch, start-ui*.sh."""

from __future__ import annotations

import os
from pathlib import Path


def is_demo() -> bool:
    """True when the deployment was launched in demo mode (PROVISA_DEMO=1/true/yes)."""
    return os.environ.get("PROVISA_DEMO", "").lower() in ("1", "true", "yes")


NAMED_DEMO_DIR_ENV = "PROVISA_NAMED_DEMO_DIR"


def named_demo() -> str | None:  # REQ-2010
    """The name of the named demo this deployment was started as (its directory's name), or None
    when none was: the UI keys the demo's own track and its words by it."""
    named = os.environ.get(NAMED_DEMO_DIR_ENV)
    return Path(named).name if named else None


def example_queries() -> list[dict[str, str]]:  # REQ-2009
    """The example GraphQL queries the named demo ships (``demo/named/<name>/queries/*.graphql``),
    in file-name order: each its file's name without the extension, and its text. The GraphQL
    explorer opens them as tabs the first time the demo is opened. None when no named demo was
    started (start-ui-install.sh --demo <name> names its directory) or it ships none."""
    named = os.environ.get(NAMED_DEMO_DIR_ENV)
    if not named:
        return []  # no named demo started: nothing ships examples
    return [
        {"name": path.stem, "query": path.read_text(encoding="utf-8")}
        for path in sorted((Path(named) / "queries").glob("*.graphql"))
    ]


def tour_answers_path(named: str) -> Path:  # REQ-2012
    """Where the demo's template build stores Polly's answers to its tour's questions:
    ``{"<step key>": {"question": ..., "answer": ...}}``."""
    return Path(named) / "tour_answers.json"


def demo_tour() -> list[dict[str, str]]:  # REQ-2010
    """The steps of the named demo's own tour (``demo/named/<name>/tour.yaml``), as written: the
    UI runs them as the demo's track, before the product tour. None when no named demo was
    started or it has no tour.

    REQ-2012: a step asking Polly a question (``polly``) carries the answer stored for it when the
    demo's template was built, as ``answer``, if one was stored for that same question; the UI
    leaves out a step with none. Nothing is asked when a visitor walks the tour."""
    import json

    import yaml

    named = os.environ.get(NAMED_DEMO_DIR_ENV)
    if not named:
        return []  # no named demo started: there is no demo tour
    path = Path(named) / "tour.yaml"
    if not path.is_file():
        return []  # a named demo without a tour of its own
    steps = yaml.safe_load(path.read_text(encoding="utf-8"))["steps"]
    answers_path = tour_answers_path(named)
    if not answers_path.is_file():
        return steps  # a demo not built from a template: no stored answers
    stored = json.loads(answers_path.read_text(encoding="utf-8"))
    for step in steps:
        entry = stored.get(step["key"]) if "polly" in step else None
        # An answer stored for another question is not this step's answer.
        if entry is not None and entry["question"] == step["polly"]:
            step["answer"] = entry["answer"]
    return steps
