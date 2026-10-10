# Copyright (c) 2026 Kenneth Stott
# Canary: fb561420-3e5d-4174-970a-207206944d60
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Where the test stack's images come from in CI: this repository's registry, not Docker Hub.

``.github/ci-images/test-stack.txt`` lists every image the container-backed tests pull, pinned
by digest. ``mirror-ci-images.yml`` copies each to ``ghcr.io/kenstott/provisa/ci-<name>`` with
its digest preserved. When ``PROVISA_CI_IMAGES=mirror`` (the suite's lanes set it), the reference
a compose file or a test asks for is turned into that copy:

- :func:`compose_override` writes a compose file that points each pulled service of a stack at
  its copy; the harness adds it last. No compose file is edited, and none an install starts
  names a mirror.
- :func:`image` does the same for a test that starts a container itself (``docker run``).

Anywhere else the references are used as written. An image that is asked for in CI and is not
in the list is refused by name: nothing is pulled from Docker Hub by accident.

    python -m tests.ci_images override <out.yml> <compose file>...   (for a shell script)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

REPO = Path(__file__).resolve().parents[1]
LIST = REPO / ".github" / "ci-images" / "test-stack.txt"
MIRROR = "ghcr.io/kenstott/provisa/ci-"
ENV = "PROVISA_CI_IMAGES"


class Entry(NamedTuple):
    name: str
    upstream: str  # <registry>/<repository>@sha256:<digest>
    asked: str  # the reference a compose file or a test writes

    @property
    def digest(self) -> str:
        return self.upstream.rsplit("@", 1)[1]

    @property
    def mirror(self) -> str:
        """The copy, addressed by the upstream digest: the same image."""
        return f"{MIRROR}{self.name}@{self.digest}"


class NotMirrored(LookupError):
    """An image the stack asks for in CI that the mirror list does not hold."""


def entries(path: Path = LIST) -> dict[str, Entry]:
    """The list, by the reference asked for."""
    found: dict[str, Entry] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"{path.name}:{number}: expected <name> <upstream@digest> <asked>")
        entry = Entry(*parts)
        if entry.asked in found:
            raise ValueError(f"{path.name}:{number}: {entry.asked} is listed twice")
        found[entry.asked] = entry
    return found


def mirroring() -> bool:
    """Whether this process pulls the copies. Only ``mirror`` turns it on; any other value is a
    mistake and is refused, so a typo cannot quietly mean Docker Hub."""
    value = os.environ.get(ENV)
    if value is None:
        return False
    if value != "mirror":
        raise ValueError(f"{ENV}={value!r}: the only value is 'mirror'")
    return True


def mirrored(reference: str) -> str:
    """The copy of ``reference``, or :class:`NotMirrored` naming it."""
    entry = entries().get(reference)
    if entry is None:
        raise NotMirrored(
            f"{reference} is not in {LIST.relative_to(REPO)}: add its line (pinned by digest) "
            "and run the mirror workflow, so CI does not pull it from its upstream registry"
        )
    return entry.mirror


def image(reference: str) -> str:
    """The image a test starts itself: its copy in CI, ``reference`` as written elsewhere."""
    return mirrored(reference) if mirroring() else reference


def pulled_services(compose_files: list[str]) -> dict[str, str]:
    """service -> image, for every service of the stack these files make that is PULLED: it has
    an image and no build. Later files override earlier ones, as compose merges them."""
    merged: dict[str, dict] = {}
    for path in compose_files:
        document = yaml.safe_load(Path(path).read_text()) or {}
        for service, body in (document.get("services") or {}).items():
            kept = {k: v for k, v in (body or {}).items() if k in ("image", "build")}
            merged.setdefault(service, {}).update(kept)
    pulled = {}
    for service, body in merged.items():
        if "image" in body and "build" not in body:
            if "$" in body["image"]:
                raise ValueError(f"{service}: image {body['image']!r} is not a literal reference")
            pulled[service] = body["image"]
    return pulled


def compose_override(compose_files: list[str], out: str) -> str | None:
    """Write the compose file that points each pulled service of this stack at its copy, and
    return its path — or None when this process does not pull the copies (nothing is written)."""
    if not mirroring():
        return None
    services = {
        service: {"image": mirrored(reference)}
        for service, reference in sorted(pulled_services(compose_files).items())
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        "# Written by tests/ci_images.py: each pulled service's image, as its copy in this\n"
        "# repository's registry (.github/ci-images/test-stack.txt). Not kept.\n"
        + yaml.safe_dump({"services": services}, sort_keys=True)
    )
    return out


def compose_args(compose_files: list[str], out: str) -> list[str]:
    """``["-f", <override>]`` to append to a compose command's files, or ``[]``."""
    path = compose_override(compose_files, out)
    return ["-f", path] if path else []


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[1] != "override":
        print(__doc__, file=sys.stderr)
        return 2
    path = compose_override(argv[3:], argv[2])
    print(path or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
