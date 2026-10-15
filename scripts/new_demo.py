# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Scaffold a named demo: demo/named/<name>/ in the shape every named demo has (docs/named-demos.md),
and its tour's words in every locale of the UI.

    python scripts/new_demo.py <name> [--title "..."] [--port 28632] [--requires 0.1.0a486]

What it writes passes scripts/check_demo.py's checks from the start, except what only the demo's
author can supply: the card's screenshot, and the translations of the tour's words (each locale
other than English starts with the English words). The template is scripts/new_demo_template/;
every TODO in it is the author's to replace.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).resolve().parent / "new_demo_template"
NAMED = ROOT / "demo" / "named"
LOCALES = ROOT / "provisa-ui" / "src" / "i18n" / "locales"

#: A demo's name is its directory, its compose project's suffix and its tour keys' prefix.
NAME = re.compile(r"[a-z][a-z0-9]*")
#: The ports the named demos' stores publish by default: 28<N>32, one block of 100 a demo.
_PORT = re.compile(r"\b28(\d)32\b")

#: The words of each step the template's tour has, in English: tour.steps.<name><Suffix>.
STEP_WORDS = {
    "Scenario": (
        "What this demo is",
        "TODO: the scenario, its question and the features it shows.",
    ),
    "Tables": ("The tables", "TODO: the tables the sources become."),
    "Join": ("How they join", "TODO: the relationship that joins the tables."),
    "Answer": ("The answer in SQL", "TODO: the predesigned query that answers the question."),
    "Example": ("The answer in GraphQL", "TODO: the example query, and what it shows."),
    "Recap": ("What you saw", "TODO: the recap, and where to go next."),
}


def next_port(named: Path = NAMED) -> int:
    """The first 28<N>32 no named demo's compose files publish."""
    used = {
        int(m.group(1))
        for compose in named.glob("*/docker-compose*.yml")
        for m in _PORT.finditer(compose.read_text())
    }
    free = [n for n in range(1, 10) if n not in used]
    if not free:
        raise SystemExit("every 28<N>32 is a named demo's: pass --port")
    return 28032 + free[0] * 100


def latest_release() -> str:
    """The newest release tag as a Python version (v0.1.0-alpha.486 -> 0.1.0a486)."""
    tags = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--list", "v*", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not tags:
        raise SystemExit("no v* release tag in this checkout: pass --requires")
    m = re.fullmatch(r"v(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?", tags[0])
    if m is None:
        raise SystemExit(
            f"release tag {tags[0]} is not v<x.y.z>[-alpha|beta|rc.<n>]: pass --requires"
        )
    base, kind, n = m.groups()
    return base if kind is None else f"{base}{ {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}[kind] }{n}"


def _fill(text: str, values: dict[str, str]) -> str:
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def scaffold(
    name: str,
    *,
    title: str,
    port: int,
    requires: str,
    named: Path = NAMED,
    locales: Path = LOCALES,
) -> Path:
    """Write demo/named/<name>/ and the tour's words in every locale; refused by name when the
    name is not one a demo can have or the demo exists."""
    if NAME.fullmatch(name) is None:
        raise SystemExit(
            f"{name!r}: a demo's name is lower-case letters and digits, a letter first"
        )
    home = named / name
    if home.exists():
        raise SystemExit(f"{home} exists: a new demo needs a name no demo has")
    values = {
        "__TITLE__": title,
        "__REQUIRES__": requires,
        "__DOMAIN__": name,
        "__PREFIX__": f"{name[0]}__",
        "__ENV__": name.upper(),
        "__PORT__": str(port),
        "__NAME__": name,
    }
    shutil.copytree(TEMPLATE, home, ignore=shutil.ignore_patterns("__pycache__"))
    for path in sorted(p for p in home.rglob("*") if p.is_file()):
        lines = path.read_text().splitlines(keepends=True)
        # The template's own canary stamps are its, not the demo's: the commit stamps the demo.
        kept = "".join(line for line in lines if "Canary:" not in line)
        path.write_text(_fill(kept, values))
    _add_words(name, title, locales)
    return home


def _add_words(name: str, title: str, locales: Path) -> None:
    """tour.steps.<name><Suffix> and tour.demos.<name> in every locale's tour.json: English
    everywhere, for the i18n-translate pass to translate."""
    for tour in sorted(locales.glob("*/tour.json")):
        doc = json.loads(tour.read_text())
        words = doc["tour"]
        for suffix, (step_title, description) in STEP_WORDS.items():
            words["steps"][f"{name}{suffix}"] = {"title": step_title, "description": description}
        words["demos"][name] = {"title": title, "summary": f"TODO: {title}, in one sentence."}
        tour.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a named demo.")
    parser.add_argument("name", help="the demo's name: lower-case letters and digits")
    parser.add_argument("--title", help="the demo's title (default: the name)")
    parser.add_argument("--port", type=int, help="its database's port (default: the next free)")
    parser.add_argument("--requires", help="requires_provisa (default: the newest release tag)")
    args = parser.parse_args(argv)
    home = scaffold(
        args.name,
        title=args.title or args.name.capitalize(),
        port=args.port or next_port(),
        requires=args.requires or latest_release(),
    )
    print(f"wrote {home.relative_to(ROOT)}; next: python scripts/check_demo.py {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
