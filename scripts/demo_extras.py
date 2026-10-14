#!/usr/bin/env python3
# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The packages a named demo needs beyond a plain install (REQ-2016).

A demo names the optional dependency groups of pyproject.toml it needs in its demo.yaml
(``extras: [vector]``); this prints the requirement of each package those groups list, one a
line, for start-ui-install.sh to install for that demo alone. A demo that names none prints
nothing. A group pyproject.toml does not have is refused by name.

Usage: demo_extras.py <demo dir>
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def requirements(demo_dir: Path) -> list[str]:
    spec = yaml.safe_load((demo_dir / "demo.yaml").read_text()) or {}
    extras = spec.get("extras") or []
    groups = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]
    out: list[str] = []
    for extra in extras:
        if extra not in groups:
            raise SystemExit(
                f"{demo_dir.name}/demo.yaml names extra {extra!r}, which pyproject.toml does not "
                f"have (it has {', '.join(sorted(groups))})"
            )
        out.extend(r for r in groups[extra] if r not in out)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: demo_extras.py <demo dir>")
    for requirement in requirements(Path(sys.argv[1])):
        print(requirement)
