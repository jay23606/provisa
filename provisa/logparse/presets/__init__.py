# Copyright (c) 2026 Kenneth Stott
# Canary: a3eb0b29-431b-4501-a244-89004ab52760
#
# This source code is licensed under the Business Source License 1.1
"""The named presets over the shared parsers (REQ-1996), one module per family (amazon,
microsoft, google, web, databases, linux, security). Each module states ``PRESETS``: a list of
:class:`provisa.logparse.base.Format`, each with a unique ``name`` and the family as its
``group``. They are found here by module, so a family is added by adding its file."""

from __future__ import annotations

import importlib
import pkgutil

from provisa.logparse.base import Format


def presets() -> list[Format]:
    """Every family's presets, by module name, in the order each module lists them."""
    found: list[Format] = []
    for module in sorted(m.name for m in pkgutil.iter_modules(__path__)):
        found.extend(importlib.import_module(f"{__name__}.{module}").PRESETS)
    return found
