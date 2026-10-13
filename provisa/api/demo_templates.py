# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The published named demos, and the template org each one's sandboxes are cloned from (REQ-2006).

A named demo is ``demo/named/<name>/``: its ``config.yaml`` (the whole config, REQ-1858) and its
``demo.yaml`` (title, description, screenshot, ``published``). Only a published demo is offered as a
sandbox; an unknown or unpublished name is refused by name.

Each published demo has a template org, ``sbxtpl<name>`` (sandbox_tier.template_org_id), on the
sandbox tier. It is a demo organisation (REQ-1919): every build of its runtime rebuilds its model
from the demo's configuration, and its replicas are landed into its own DuckDB file when the tier
starts -- once, at deploy time. A visitor's sandbox is a copy of it (demo_sandbox.py).

The configuration names its own directory as ``${env:PROVISA_NAMED_DEMO_DIR}`` (the weblogs demo's
log globs). One process serves every published demo, so that reference is replaced here by the
demo's directory instead of read from one process-wide variable.
"""

# Requirements: REQ-2006, REQ-1858, REQ-1919

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from provisa.api.errors import ApiError
from provisa.api.sandbox_tier import TEMPLATE_PREFIX, is_template_org, template_org_id
from provisa.core.replicate import ALWAYS

_DEMO_DIR_REF = "${env:PROVISA_NAMED_DEMO_DIR}"
_PKG_NAMED = Path(__file__).resolve().parents[1] / "_config" / "demo" / "named"
_REPO_NAMED = Path(__file__).resolve().parents[2] / "demo" / "named"


def named_demos_dir() -> Path:
    """Where the named demos are: ``$PROVISA_NAMED_DEMOS_DIR`` when the deployment says, else the
    wheel-staged copy (REQ-1127), else the source checkout's ``demo/named``."""
    configured = os.environ.get("PROVISA_NAMED_DEMOS_DIR")
    if configured:
        return Path(configured)
    return _PKG_NAMED if _PKG_NAMED.is_dir() else _REPO_NAMED


@dataclass(frozen=True)
class PublishedDemo:
    name: str
    title: str
    directory: Path

    @property
    def template_org(self) -> str:
        return template_org_id(self.name)


def published_demos() -> dict[str, PublishedDemo]:
    """Every named demo whose demo.yaml says ``published: true``, by name."""
    root = named_demos_dir()
    found: dict[str, PublishedDemo] = {}
    for spec_file in sorted(root.glob("*/demo.yaml")):
        spec = yaml.safe_load(spec_file.read_text())
        published = spec.get("published")
        if not isinstance(published, bool):
            raise ValueError(f"{spec_file}: published must be true or false")
        if published:
            name = spec_file.parent.name
            found[name] = PublishedDemo(name=name, title=spec["title"], directory=spec_file.parent)
    return found


def published_demo(name: str) -> PublishedDemo:
    """The published demo ``name``; refused by name when there is none."""
    demo = published_demos().get(name)
    if demo is None:
        raise ApiError(
            404,
            "sandbox.unknown_demo",
            f"No published demo named {name!r}",
            demo=name,
        )
    return demo


def demo_of_template(org_id: str) -> PublishedDemo:
    """The published demo whose template org ``org_id`` is."""
    assert is_template_org(org_id), org_id
    return published_demo(org_id[len(TEMPLATE_PREFIX) :])


def _with_directory(node: Any, directory: str) -> Any:
    if isinstance(node, str):
        return node.replace(_DEMO_DIR_REF, directory)
    if isinstance(node, list):
        return [_with_directory(item, directory) for item in node]
    if isinstance(node, dict):
        return {key: _with_directory(value, directory) for key, value in node.items()}
    return node


def template_seed(org_id: str) -> Any:  # a ProvisaConfig
    """The configuration template org ``org_id`` is rebuilt from: its demo's config.yaml, with the
    demo's directory written in."""
    from provisa.core.config_loader import parse_config_dict, read_config_with_includes

    demo = demo_of_template(org_id)
    raw = _with_directory(
        read_config_with_includes(demo.directory / "config.yaml"), str(demo.directory)
    )
    for source in raw.get("sources", []):
        # Pre-seeded: every table of the demo is read from its replica (REQ-826 ``replicate: 0``,
        # always), landed into the template's file once, and copied into each sandbox's file. A
        # sandbox's reads never reach the demo's shared sources.
        source["replicate"] = ALWAYS
    return parse_config_dict(raw)


async def ensure_demo_templates(pool) -> dict[str, str]:
    """Create and build the template org of every published demo that does not have a ready one.

    Run by the sandbox tier at startup -- deploy time -- and never on a visitor's request. The
    build is the create path's own (orgs_router._provision_org_task), with the demo seeded: the
    template is a demo organisation (``seeded_demo``), so its model is the demo's configuration.
    Its replicas are then landed by the ordinary replica convergence, since the template's sources
    replicate always (template_seed). What each demo's template did: ``"ready"`` or
    ``"building"``."""
    from sqlalchemy import select, update

    from provisa.core.connection_loop import spawn_background
    from provisa.core.schema_admin import orgs

    outcome: dict[str, str] = {}
    for demo in published_demos().values():
        org_id = demo.template_org
        async with pool.acquire() as conn:
            row = (
                await conn.execute_core(
                    select(orgs.c.provisioning_state).where(orgs.c.id == org_id)
                )
            ).fetchone()
            if row is None:
                await conn.execute_core(
                    orgs.insert().values(
                        id=org_id,
                        name=f"Demo template: {demo.title}",
                        created_by=None,
                        provisioning_state="provisioning",
                        seeded_demo=True,
                    )
                )
            elif row[0] == "ready":
                outcome[demo.name] = "ready"
                continue
            else:
                await conn.execute_core(
                    update(orgs)
                    .where(orgs.c.id == org_id)
                    .values(provisioning_state="provisioning", provisioning_error=None)
                )
        from provisa.api.admin.orgs_router import _provision_org_task

        task = spawn_background(
            _provision_org_task(org_id, True, None, False), name=f"demo-template-{demo.name}"
        )
        _build_tasks.add(task)
        task.add_done_callback(_build_tasks.discard)
        outcome[demo.name] = "building"
    return outcome


_build_tasks: set = set()
