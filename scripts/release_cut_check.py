# Copyright (c) 2026 Kenneth Stott
# Canary: 8830694f-2fb6-4fef-8ba8-25e9c4039dac
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Whether a release can be cut at HEAD, and from which release its notes start.

Run by the "Release: cut" workflow (.github/workflows/release-cut.yml) before anything is written.
It refuses, exiting 2 with the reason:

- a version not shaped as a release tag (v0.1.0, v0.1.0-alpha.480, -beta.N, -rc.N);
- a tag that already exists;
- a docs/releases/<version>.md that someone wrote: the notes generator would overwrite it. A
  page this same cut wrote, on an earlier attempt that did not finish, is its own and is
  written again;
- a HEAD with no earlier release tag to start the notes from.

Run again with ``--written`` after the generator, it refuses a hand-written page under
docs/releases that the generator changed or removed.

On success it prints ``previous=<tag>`` for the workflow's step outputs.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - argv-list git invocations only, never shell=True
import sys
from pathlib import Path

VERSION = re.compile(r"^v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")


def cut_subject(version: str) -> str:
    """The subject of the commit the cut makes: how a page it wrote is told from a hand-written
    one."""
    return f"chore(release): {version} notes"


class CutRefused(Exception):
    pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 B607 - fixed git argv, no shell
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def check(repo: Path, version: str) -> str:
    """The previous release's tag, when ``version`` can be cut at ``repo``'s HEAD."""
    if not VERSION.match(version):
        raise CutRefused(
            f"{version!r} is not a release tag (v0.1.0, or with -alpha.N, -beta.N or -rc.N)"
        )
    if _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{version}").returncode == 0:
        raise CutRefused(f"the tag {version} already exists")
    page = Path("docs/releases") / f"{version}.md"
    if (repo / page).exists():
        last = _git(repo, "log", "-1", "--format=%s", "--", str(page)).stdout.strip()
        if last != cut_subject(version):
            raise CutRefused(
                f"{page} is already in the tree (last written by {last!r}), and the notes "
                "generator would overwrite it; move or rename the hand-written page first"
            )
    previous = _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD")
    if previous.returncode != 0:
        raise CutRefused(
            f"HEAD has no earlier release tag to start the notes from: {previous.stderr.strip()}"
        )
    return previous.stdout.strip()


def check_written(repo: Path, version: str) -> None:
    """After the generator ran: every page it changed under docs/releases is this release's, or
    one an earlier cut wrote for its own release (the generator drops those of releases before
    the first one shown). A hand-written page it changed or removed refuses the cut by name."""
    changed = _git(repo, "status", "--porcelain", "--", "docs/releases").stdout.splitlines()
    own = f"docs/releases/{version}.md"
    foreign = []
    for line in changed:
        path = line[3:].strip()
        if path == own:
            continue
        stem = Path(path).stem
        last = _git(repo, "log", "-1", "--format=%s", "--", path).stdout.strip()
        if last != cut_subject(stem):
            foreign.append(f"{path} ({line[:2].strip()}; last written by {last!r})")
    if foreign:
        raise CutRefused(
            "the notes generator changed hand-written release pages: " + "; ".join(foreign)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a release can be cut at HEAD.")
    parser.add_argument("--version", required=True, help="the release tag to cut")
    parser.add_argument("--repo", type=Path, default=Path("."), help="the repository (default: .)")
    parser.add_argument(
        "--written",
        action="store_true",
        help="after the notes were generated: check no hand-written page was changed",
    )
    args = parser.parse_args(argv)
    try:
        if args.written:
            check_written(args.repo, args.version)
            return 0
        previous = check(args.repo, args.version)
    except CutRefused as refused:
        print(f"ERROR: {refused}", file=sys.stderr)
        return 2
    print(f"previous={previous}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
