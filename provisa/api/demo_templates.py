# Copyright (c) 2026 Kenneth Stott
# Canary: dddd1887-185b-47b0-b4bd-a80f7ddf6894
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
from collections.abc import Awaitable, Callable
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


#: What runs once a demo's template is built and every one of its replicas is landed, at each
#: start of the sandbox tier: ``hook(demo, template_org)``, with the template's runtime built and the
#: template org bound. Registered by what derives something of its own from a template at deploy
#: time (the tour answers). A hook that raises is logged and the next one still runs; the template
#: stays usable.
TemplateHook = Callable[[PublishedDemo, str], Awaitable[None]]
_ready_hooks: list[TemplateHook] = []

#: How often a template being prepared is asked whether its replicas have landed.
_LANDED_POLL_S = 2.0


def on_template_ready(hook: TemplateHook) -> TemplateHook:
    """Register ``hook`` to run when a template is ready (see ``_ready_hooks``)."""
    _ready_hooks.append(hook)
    return hook


async def ensure_demo_templates(pool) -> dict[str, str]:
    """Create and build the template org of every published demo that does not have a ready one,
    then wait for each template's replicas to land and run the ready hooks.

    Run by the sandbox tier at startup -- deploy time -- and never on a visitor's request. The
    build is the create path's own (orgs_router._provision_org_task), with the demo seeded: the
    template is a demo organisation (``seeded_demo``), so its model is the demo's configuration.
    Its replicas are then landed by the ordinary replica convergence, since the template's sources
    replicate always (template_seed). What each demo's template did: ``"ready"`` (built before;
    its runtime is built now) or ``"building"``."""
    from sqlalchemy import select, update

    from provisa.core.connection_loop import spawn_background
    from provisa.core.schema_admin import orgs

    outcome: dict[str, str] = {}
    for demo in published_demos().values():
        org_id = demo.template_org
        build = True
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
                build = False
            else:
                await conn.execute_core(
                    update(orgs)
                    .where(orgs.c.id == org_id)
                    .values(provisioning_state="provisioning", provisioning_error=None)
                )
        task = spawn_background(_prepare(demo, build), name=f"demo-template-{demo.name}")
        _build_tasks.add(task)
        task.add_done_callback(_build_tasks.discard)
        outcome[demo.name] = "building" if build else "ready"
    return outcome


async def _prepare(demo: PublishedDemo, build: bool) -> None:
    """Build (or only load) the template, wait until every replica it declares has landed, then
    run the ready hooks. A replica whose build failed stops the wait: the template is not ready,
    and a visitor is told so by name (demo_sandbox._template_ready)."""
    import asyncio
    import logging

    from provisa.api.admin.orgs_router import _provision_org_task
    from provisa.api.app import ensure_org_runtime
    from provisa.core.request_context import reset_current_org, set_current_org

    log = logging.getLogger(__name__)
    org_id = demo.template_org
    if build:
        await _provision_org_task(org_id, True, None, False)
    rt = await ensure_org_runtime(org_id)
    while True:
        landed, failed, declared = await _replica_progress(rt)
        if failed:
            log.error("demo template %s: replicas failed to land: %s", demo.name, failed)
            return
        # Every table of a template is replicated always (template_seed): it is ready when each
        # one registered has a landed replica, whether or not convergence has asked for all yet.
        if landed >= declared:
            break
        await asyncio.sleep(_LANDED_POLL_S)
    log.info("demo template %s: every replica landed", demo.name)
    token = set_current_org(org_id)
    try:
        for hook in _ready_hooks:
            try:
                await hook(demo, org_id)
            except Exception:  # allow-ble: one deploy-time derivation failing leaves the template usable and the next hook still runs; logged with its cause
                log.exception("demo template %s: ready hook %r failed", demo.name, hook)
    finally:
        reset_current_org(token)


async def _replica_progress(rt) -> tuple[int, list[str], int]:
    """How many of the template's replicas have landed, the tables whose last build failed, and
    how many tables the template registers."""
    from sqlalchemy import func, select

    from provisa.core.schema_org import registered_tables, replica_state

    async with rt.tenant_db.acquire() as conn:
        rows = (
            await conn.execute_core(
                select(
                    replica_state.c.table_name,
                    replica_state.c.build_state,
                    replica_state.c.completed_at,
                ).where(replica_state.c.retired_at.is_(None))
            )
        ).fetchall()
    async with rt.model_db.acquire() as conn:
        declared = int(
            (
                await conn.execute_core(select(func.count()).select_from(registered_tables))
            ).scalar_one()
        )
    landed = sum(1 for r in rows if r[2] is not None)
    failed = [r[0] for r in rows if r[1] == "failed" and r[2] is None]
    return landed, failed, declared


_build_tasks: set = set()
