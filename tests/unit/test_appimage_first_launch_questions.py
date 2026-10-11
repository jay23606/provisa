# Copyright (c) 2026 Kenneth Stott
# Canary: 787bc268-0e49-4054-99a1-0c6659fca744
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A question the Linux AppImage's first launch asks is not part of its answer (#214).

An interactive first launch wrote ``api_port: API port [8000]: 8000`` into the configuration —
and a hostname the same way — and ``provisa start`` failed on the port. ``write_config``
captures ``ask_hostname`` and ``ask_api_port`` as the answer, and each printed its question to
standard output too: the question was captured with the answer, and on a terminal never shown.

The functions are run here as the script runs them (``bash -euo pipefail``), with the answer
typed on stdin."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_FIRST_LAUNCH = (Path(__file__).parents[2] / "packaging/linux/first-launch.sh").read_text()


def _function(name: str) -> str:
    start = _FIRST_LAUNCH.index(f"{name}() {{")
    return _FIRST_LAUNCH[start : _FIRST_LAUNCH.index("\n}\n", start) + 3]


@pytest.mark.parametrize(
    ("function", "typed", "answer"),
    [
        ("ask_api_port", "\n", "8000"),  # Enter: the default
        ("ask_api_port", "9001\n", "9001"),
        ("ask_api_port", "80\n9001\n", "9001"),  # refused, asked again
        ("ask_hostname", "db1.example\n", "db1.example"),
    ],
)
def test_the_answer_is_the_answer_alone_and_the_question_is_still_asked(function, typed, answer):
    script = (
        "NON_INTERACTIVE=false\n"
        + _function(function)
        + f'answer="$({function})"\nprintf "%s" "$answer"\n'
    )
    done = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        input=typed,
        # This process's own PATH: a fixed one names directories that hold no bash on NixOS.
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == answer
    assert "[" in done.stderr  # asked where a person sees it


def test_every_answer_first_launch_captures_comes_from_a_function_that_asks_on_stderr():
    captured = set(re.findall(r'="\$\((ask_\w+)\)"', _FIRST_LAUNCH))
    assert captured == {"ask_hostname", "ask_api_port"}
    for function in captured:
        for line in _function(function).splitlines():
            if line.strip().startswith("printf"):
                assert ">&2" in line, line
