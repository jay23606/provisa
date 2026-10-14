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

Where the demos come from (REQ-2049). A deployment names the demos it offers in
``PROVISA_DEMO_BUNDLES`` and pulls each one's published bundle (provisa/core/demo_bundles.py) from
``PROVISA_DEMO_REGISTRY``: at start, and again whenever a sandbox of it is opened, so a demo
published since is served with no redeploy. A newer bundle replaces the demo's template: the old
one is removed whole and the new one landed from the new bundle's seed before the sandbox is
cloned; a sandbox already open keeps what it was cloned from. Without ``PROVISA_DEMO_BUNDLES`` the
demos are the directories under ``named_demos_dir()`` -- a source checkout's, for development, and
the bundle build's own.
"""

# Requirements: REQ-2006, REQ-1858, REQ-1919, REQ-2049

from __future__ import annotations

import asyncio
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


def bundled_demos() -> tuple[str, ...]:
    """The demos this deployment pulls as bundles (``PROVISA_DEMO_BUNDLES``, comma-separated);
    none when it serves the directories under ``named_demos_dir()`` instead."""
    listed = os.environ.get("PROVISA_DEMO_BUNDLES", "")
    return tuple(name.strip() for name in listed.split(",") if name.strip())


def bundles_root() -> Path:
    """Where pulled bundles are unpacked: ``<data dir>/demo-bundles/<name>/<version>``, with
    ``<name>/current`` naming the version served."""
    from provisa.core.org_files import data_dir

    return data_dir() / "demo-bundles"


def _registry() -> Any:
    from provisa.core.demo_bundles import Registry

    return Registry(os.environ["PROVISA_DEMO_REGISTRY"])


def _served_version(name: str) -> str | None:
    current = bundles_root() / name / "current"
    return current.read_text().strip() if current.exists() else None


def pull_latest(name: str) -> bool:
    """Pull demo ``name``'s latest bundle when it is not the one served, and serve it; whether it
    changed. Blocking: run in a thread."""
    from provisa.core.demo_bundles import LATEST, running_provisa

    registry = _registry()
    _digest, oci_manifest = registry.resolve(name, LATEST)
    version = registry.manifest_of(name, oci_manifest).version
    if version == _served_version(name):
        return False
    target = bundles_root() / name / version
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        registry.pull(name, version, target, running_provisa())
    staged = target.parent / ".current"
    staged.write_text(version + "\n")
    staged.replace(target.parent / "current")
    return True


def _demo_directories() -> list[Path]:
    """Each named demo's directory: the version served of each bundled demo, else every one under
    ``named_demos_dir()``."""
    names = bundled_demos()
    if not names:
        return [spec.parent for spec in sorted(named_demos_dir().glob("*/demo.yaml"))]
    found = []
    for name in names:
        version = _served_version(name)
        if version is None:
            raise RuntimeError(
                f"demo {name} has no bundle pulled; the sandbox tier pulls it at start"
            )
        found.append(bundles_root() / name / version)
    return found


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
    found: dict[str, PublishedDemo] = {}
    bundled = bool(bundled_demos())
    for directory in _demo_directories():
        spec_file = directory / "demo.yaml"
        spec = yaml.safe_load(spec_file.read_text())
        published = spec.get("published")
        if not isinstance(published, bool):
            raise ValueError(f"{spec_file}: published must be true or false")
        if published:
            # A bundle's directory is its version; the demo is the directory above it.
            name = directory.parent.name if bundled else directory.name
            found[name] = PublishedDemo(name=name, title=spec["title"], directory=directory)
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
    _sandbox_sees_what_its_rights_cover(raw, _role_rights(raw))
    for source in raw.get("sources", []):
        # Pre-seeded: every table of the demo is read from its replica (REQ-826 ``replicate: 0``,
        # always), landed into the template's file once, and copied into each sandbox's file. A
        # sandbox's reads never reach the demo's shared sources.
        source["replicate"] = ALWAYS
        # And landed once: a demo's data is fixed, so a replica is refreshed only when something
        # signals a change (REQ-932 ``signal``), never re-read on a cadence -- not by the template,
        # and not by a sandbox, which carries the template's model.
        source["change_signal"] = "signal"
    return parse_config_dict(raw)


def _role_rights(raw: dict) -> dict[str, frozenset[str]]:
    """Each role a demo's configuration can name, with its rights: the seeded roles, and the
    demo's own (flattened, inheritance included), which stand in for a seeded one of the same id."""
    from provisa.core.db import SEEDED_ROLE_RIGHTS
    from provisa.core.models import Role, flatten_roles

    rights = dict(SEEDED_ROLE_RIGHTS)
    own = flatten_roles([Role(**role) for role in raw.get("roles", [])])
    rights.update({role.id: frozenset(role.capabilities) for role in own})
    return rights


def _sandbox_sees_what_its_rights_cover(node: Any, rights: dict[str, frozenset[str]]) -> None:
    """A demo names who sees each column and table as it would anywhere (its admin, its own
    roles). Its sandbox's person holds the sandbox role (REQ-1597): wherever a role holding every
    right the sandbox role holds is named, the sandbox role is named with it."""
    from provisa.api.demo_sandbox import SANDBOX_ROLE

    covered = rights[SANDBOX_ROLE]
    if isinstance(node, list):
        for item in node:
            _sandbox_sees_what_its_rights_cover(item, rights)
    elif isinstance(node, dict):
        visible = node.get("visible_to")
        if (
            isinstance(visible, list)
            and SANDBOX_ROLE not in visible
            and any(covered <= rights.get(role_id, frozenset()) for role_id in visible)
        ):
            visible.append(SANDBOX_ROLE)
        for value in node.values():
            _sandbox_sees_what_its_rights_cover(value, rights)


def demo_roles(template_org: str) -> list[str]:
    """The roles a demo's configuration defines for itself (its analyst, say), which a sandbox's
    person also holds so the demo's tour can run as each. One that would carry a right the sandbox
    role withholds (REQ-1597), on its own or by inheritance, is refused by name rather than
    granted."""
    from provisa.core.db import SANDBOX_DENIED
    from provisa.core.models import flatten_roles

    out = []
    for role in flatten_roles(list(template_seed(template_org).roles)):
        withheld = sorted(set(role.capabilities) & SANDBOX_DENIED)
        if withheld:
            raise ValueError(
                f"demo role {role.id!r} of {template_org} holds {', '.join(withheld)}, which a "
                "sandbox's person may not (REQ-1597)"
            )
        out.append(role.id)
    return out


def replicated_tables(config: Any) -> list[Any]:
    """The tables of a demo's configuration that have a replica: every one read from a source.
    Its views (DERIVED_SOURCE_ID: defined by their SQL, read from the tables) have none, so a
    template is landed when each of these is."""
    from provisa.core.models import DERIVED_SOURCE_ID

    return [table for table in config.tables if table.source_id != DERIVED_SOURCE_ID]


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


def seeding_release() -> bool:
    """Whether this process is a bundle build's seeding run (``PROVISA_DEMO_SEED_EXPORT=true``):
    each template is landed from its demo's own sources and written out as the demo's seed
    (demo_replicas.export_seed). Otherwise a template is landed from the seed its bundle carries."""
    from provisa.core.demo_bundles import seeding_run

    return seeding_run()


async def land_from_seed(org_id: str) -> None:
    """In the template org ``org_id``'s runtime build, with its model loaded and the org bound,
    before its replica convergence is wired: land its replicas from the demo's seed when this
    deployment's store does not hold them (demo_replicas.adopt_seed). A bundle build's seeding
    run lands them from the demo's sources instead, and writes the seed."""
    import logging

    from provisa.api.demo_replicas import adopt_seed, landed_here

    if seeding_release():
        return
    demo = demo_of_template(org_id)
    if await landed_here(org_id) >= len(replicated_tables(template_seed(org_id))):
        return
    if await adopt_seed(org_id, demo.directory):
        logging.getLogger(__name__).info("demo template %s: landed from its seed", demo.name)


async def ensure_demo_templates(pool) -> dict[str, str]:
    """Create and build the template org of every published demo that does not have a ready one,
    then wait for each template's replicas to land and run the ready hooks.

    Run by the sandbox tier at startup -- deploy time -- and never on a visitor's request. The
    build is the create path's own (orgs_router._provision_org_task), with the demo seeded: the
    template is a demo organisation (``seeded_demo``), so its model is the demo's configuration.
    Its replicas are then landed by the ordinary replica convergence, since the template's sources
    replicate always (template_seed). What each demo's template did: ``"ready"`` (built before;
    its runtime is built now) or ``"building"``."""
    from provisa.core.connection_loop import spawn_background

    for name in bundled_demos():
        if await asyncio.to_thread(pull_latest, name):
            await _retire_template(name)
    outcome: dict[str, str] = {}
    for demo in published_demos().values():
        build = await _template_row(pool, demo)
        task = spawn_background(_prepare(demo, build), name=f"demo-template-{demo.name}")
        _build_tasks.add(task)
        task.add_done_callback(_build_tasks.discard)
        outcome[demo.name] = "building" if build else "ready"
    return outcome


_following: dict[str, asyncio.Lock] = {}


async def follow_latest(name: str) -> None:
    """Before a sandbox of demo ``name`` is opened: when the deployment pulls its demos as bundles
    and a newer one is published, serve it -- its template rebuilt from it, waited for here, so
    the sandbox is cloned from the new one. A registry that cannot be asked refuses the sandbox
    by name rather than serve a version it could not check."""
    import httpx

    from provisa.core.demo_bundles import BundleError, NeedsNewerProvisa

    if name not in bundled_demos():
        return
    lock = _following.setdefault(name, asyncio.Lock())
    async with lock:
        try:
            changed = await asyncio.to_thread(pull_latest, name)
        except NeedsNewerProvisa as newer:
            raise ApiError(
                503,
                "sandbox.demo_needs_newer_provisa",
                str(newer),
                demo=name,
                requires=newer.manifest.requires_provisa,
                running=newer.running,
            ) from newer
        except (BundleError, httpx.HTTPError) as unreachable:
            raise ApiError(
                503,
                "sandbox.demo_unavailable",
                f"The {name} demo's latest version could not be fetched; try again shortly",
                demo=name,
            ) from unreachable
        if not changed:
            return
        await _retire_template(name)
        from provisa.api.admin.orgs_router import _admin_pool

        demo = published_demo(name)
        await _prepare(demo, await _template_row(_admin_pool(), demo))


async def _retire_template(name: str) -> None:
    """Remove demo ``name``'s template org whole, when there is one: its bundle was replaced."""
    import shutil

    from sqlalchemy import select

    from provisa.api.admin.orgs_router import _admin_pool, destroy_org
    from provisa.core import model_change, org_files
    from provisa.core.schema_admin import orgs

    org_id = template_org_id(name)
    async with _admin_pool().acquire() as conn:
        row = (await conn.execute_core(select(orgs.c.id).where(orgs.c.id == org_id))).fetchone()
    if row is None:
        return
    async with model_change.scope(f"replace demo template {org_id}"):
        await destroy_org(org_id)
    from provisa.security.sandbox_egress import forget

    forget(org_id)
    folder = org_files.folder(org_id)
    if folder.exists():
        await asyncio.to_thread(shutil.rmtree, folder)
    import logging

    logging.getLogger(__name__).info("demo template %s removed: its bundle was replaced", org_id)


async def _template_row(pool, demo: PublishedDemo) -> bool:
    """Make sure the demo's template org has a row, marked for building unless it is ready;
    whether it is to be built."""
    from sqlalchemy import select, update

    from provisa.core.schema_admin import orgs

    org_id = demo.template_org
    build = True
    async with pool.acquire() as conn:
        row = (
            await conn.execute_core(select(orgs.c.provisioning_state).where(orgs.c.id == org_id))
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
    return build


async def _prepare(demo: PublishedDemo, build: bool) -> None:
    """Build (or only load) the template, wait until every replica it declares has landed, then
    run the ready hooks. A replica whose build failed stops the wait: the template is not ready,
    and a visitor is told so by name (demo_sandbox._template_ready)."""
    import logging

    from provisa.api.admin.orgs_router import _provision_org_task
    from provisa.api.app import ensure_org_runtime
    from provisa.core.request_context import reset_current_org, set_current_org

    log = logging.getLogger(__name__)
    org_id = demo.template_org
    if build:
        await _provision_org_task(org_id, True, None, False)
    rt = await ensure_org_runtime(org_id)
    from provisa.api.demo_replicas import export_seed

    exporting = seeding_release()
    while True:
        landed, failed, declared = await _replica_progress(rt)
        if failed:
            log.error("demo template %s: replicas failed to land: %s", demo.name, failed)
            return
        # Every table of a demo is replicated always (template_seed): its template is ready when
        # each one has a landed replica, whether or not convergence has asked for all yet.
        if landed >= declared:
            break
        await asyncio.sleep(_LANDED_POLL_S)
    log.info("demo template %s: every replica landed", demo.name)
    if exporting:
        await export_seed(org_id, demo.directory)
        log.info("demo template %s: seed written to %s", demo.name, demo.directory)
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
    how many replicated tables its demo's configuration declares (replicated_tables: not its
    views, and not the built-in tables every org registers)."""
    from provisa.federation import replica_state

    from provisa.api.demo_replicas import landed_here

    declared = len(replicated_tables(template_seed(rt.org_id)))
    async with rt.tenant_db.acquire() as conn:
        _recorded, failed = await replica_state.progress(conn)
    # Landed: recorded as built for this store AND held by it, rows and all.
    landed = await landed_here(rt.org_id)
    return landed, failed, declared


_build_tasks: set = set()


async def record_demo_destinations(org_id: str) -> None:
    """Record, for the sandbox org ``org_id``, the destinations its demo's configuration declares
    (provisa.security.sandbox_egress): a demo template's and a demo sandbox's are the named demo's
    sources, and the hosted sandbox org's (REQ-1598) are the deployment's demo configuration's."""
    from sqlalchemy import select

    from provisa.api.admin.orgs_router import _admin_pool
    from provisa.api.app import state
    from provisa.core.org_ids import is_sandbox_tier_org
    from provisa.core.schema_admin import demo_sandboxes
    from provisa.security.sandbox_egress import set_demo_destinations, source_fields

    if is_template_org(org_id):
        sources = template_seed(org_id).sources
    elif is_sandbox_tier_org(org_id):
        async with _admin_pool().acquire() as conn:
            row = (
                await conn.execute_core(
                    select(demo_sandboxes.c.demo).where(demo_sandboxes.c.org_id == org_id)
                )
            ).fetchone()
        if row is None:
            raise RuntimeError(f"sandbox org {org_id!r} has no demo_sandboxes row")
        sources = template_seed(template_org_id(row[0])).sources
    else:
        sources = state.seed_config.sources
    set_demo_destinations(org_id, [source_fields(s) for s in sources])
