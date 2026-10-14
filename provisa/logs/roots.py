# Copyright (c) 2026 Kenneth Stott
# Canary: 2340865d-b409-407c-885e-0cec0dce646c
#
# This source code is licensed under the Business Source License 1.1
"""Where a Logs source may read (REQ-1996). The maintainer's ruling: an operator setting
``logs.allowed_roots``, by default ``["/var/log"]``, lists the directories a glob may resolve
into; a glob, or a file it matches, that resolves outside them after following symlinks is
refused by name; on the multi-organisation SaaS plane a server-local log path is refused
entirely, by name.

The one many-organisation server that reads log files of its own is a demo bundle's seeding run
(REQ-2049): a throwaway sandbox tier the bundle build starts, holding only the demos' templates,
which lands a demo's Logs sources from the files the demo's traffic wrote into the build's copy
of the demo -- still only inside the allowed roots the build lists (that copy). A deployment's
sandbox tier lands them from the bundle's seed and reads no log file."""

from __future__ import annotations

import os
import re

from provisa.core import settings_registry
from provisa.core.secrets_providers import many_organisations

_WILDCARD = re.compile(r"[*?\[]")


class LogPathRefused(PermissionError):
    """A path a Logs source may not read; the message names it and why."""


def allowed_roots() -> list[str]:
    """The directories a glob may resolve into, as the operator listed them, each resolved."""
    return [
        os.path.realpath(os.path.expanduser(root))
        for root in settings_registry.value("logs.allowed_roots")
    ]


def _inside(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _refuse_on_saas(path: str) -> None:
    from provisa.core.demo_bundles import seeding_run

    if many_organisations() and not seeding_run():
        raise LogPathRefused(
            f"{path}: a server that holds many organizations reads no log file of its own"
        )


def checked_glob(glob: str) -> str:
    """``glob`` with ``~`` expanded, when the directory it starts from resolves inside an
    allowed root; refused by name otherwise, and always on a server of many organizations."""
    _refuse_on_saas(glob)
    expanded = os.path.expanduser(glob)
    if not os.path.isabs(expanded):
        raise LogPathRefused(f"{glob}: name the files by their full path")
    parts = expanded.split(os.sep)
    fixed = next((i for i, part in enumerate(parts) if _WILDCARD.search(part)), len(parts))
    base = os.sep.join(parts[:fixed]) or os.sep
    real = os.path.realpath(base)
    roots = allowed_roots()
    if not _inside(real, roots):
        raise LogPathRefused(
            f"{glob} resolves to {real}, outside the directories log files may be read from: "
            f"{', '.join(roots) or 'none are listed'}"
        )
    return expanded


def checked_file(path: str) -> str:
    """``path`` resolved, when it is inside an allowed root once its symlinks are followed;
    refused by name otherwise."""
    _refuse_on_saas(path)
    real = os.path.realpath(path)
    roots = allowed_roots()
    if not _inside(real, roots):
        raise LogPathRefused(
            f"{path} resolves to {real}, outside the directories log files may be read from: "
            f"{', '.join(roots) or 'none are listed'}"
        )
    return real
