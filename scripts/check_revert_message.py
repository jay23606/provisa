#!/usr/bin/env python3
# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""commit-msg check: a commit that reverts names the commit it undoes, in git's own words.

A subject starting `revert:` or `revert(<scope>):` is refused unless the body has
"This reverts commit <sha>" naming a commit that exists. The release notes leave out a reverted
commit and its revert by that line (scripts/gen_release_notes.py); without it the reverted
change would be published as shipped.

Usage (pre-commit, commit-msg stage): check_revert_message.py <commit message file>
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REVERT_SUBJECT = re.compile(r"^revert(\([^)]*\))?!?:")
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def problem(message: str) -> str | None:
    """Why the message is refused, or None."""
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    if not lines or not _REVERT_SUBJECT.match(lines[0]):
        return None
    named = _REVERTS.findall("\n".join(lines[1:]))
    if not named:
        return (
            "A revert names the commit it undoes. Add this line to the message body:\n"
            "    This reverts commit <sha of the reverted commit>.\n"
            "(git revert writes it for you; the release notes leave out the reverted commit by it.)"
        )
    for sha in named:
        found = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, text=True
        )
        if found.returncode != 0:
            return f"'This reverts commit {sha}' names no commit in this repository. Give the reverted commit's sha."
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_revert_message.py <commit message file>", file=sys.stderr)
        return 2
    reason = problem(Path(argv[0]).read_text())
    if reason is None:
        return 0
    print(f"commit refused: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
