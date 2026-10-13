# Copyright (c) 2026 Kenneth Stott
# Canary: 219dd772-5a21-4f45-ade3-aaa960aeb834
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Opening, keeping and reaping demo sandboxes (REQ-2006).

A demo sandbox is an org of its own (``sbx<hex>``), opened from the live demos page as a copy of
its demo's template org (demo_templates.py), on the sandbox tier (sandbox_tier.py):

- its model is the template's, cloned schema to schema (env_copy.clone_model), with every source's
  connection carried as it is, so it reads the demo's shared sources, which take no writes;
- its data is the template's replicas, copied from the template's DuckDB file into its own
  (materialize_broker.copy_schema) and recorded as built for its own store, so nothing of the demo
  is seeded at a visitor's request;
- its visitor is a user minted for it, holding the ``sandbox`` role (REQ-1597: org_admin's rights
  but environments and user management) and a personal access token (REQ-1263) the browser keeps
  (REQ-1035 rejected anonymous identity-provider sign-in: the visitor needs no account).

How many sandboxes may be open at once is ``sandbox.max_concurrent``; past it, a visitor is asked
to try again shortly. A sandbox no request has reached for ``sandbox.idle_ttl`` seconds is deleted
whole -- its org, its folder and its file, its engine, and its visitor's token.
"""

# Requirements: REQ-2006, REQ-1597, REQ-1263, REQ-1035, REQ-1600

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select, update

from provisa.api.demo_templates import PublishedDemo, published_demo
from provisa.api.errors import ApiError
from provisa.api.sandbox_tier import new_sandbox_org_id
from provisa.core import settings_registry
from provisa.core.schema_admin import demo_sandboxes, orgs, user_profiles

log = logging.getLogger(__name__)

VISITOR = "visitor"
NAMED = "named"
#: The role a sandbox's person holds (provisa/core/db.py, REQ-1597).
SANDBOX_ROLE = "sandbox"
_TOKEN_NAME = "Demo sandbox"

# One process serves every sandbox (sandbox_tier.py), so this lock is the whole of the count's
# protection: two visitors arriving at once cannot both take the last place.
_opening = asyncio.Lock()


@dataclass(frozen=True)
class OpenedSandbox:
    org_id: str
    demo: str
    user_id: str
    #: The visitor's personal access token; None for a named sandbox, whose person signs in.
    token: str | None


def visitor_user_id(org_id: str) -> str:
    """The user minted for a visitor's sandbox: its own, and nobody else's."""
    return f"sandbox-visitor-{org_id}"


async def _template_ready(demo: PublishedDemo) -> None:
    """Refuse by name when the demo's template is not built, or its replicas are not all landed."""
    from provisa.api.admin.orgs_router import _admin_pool
    from provisa.api.app import ensure_org_runtime

    async with _admin_pool().acquire() as conn:
        row = (
            await conn.execute_core(
                select(orgs.c.provisioning_state).where(orgs.c.id == demo.template_org)
            )
        ).fetchone()
    ready = row is not None and row[0] == "ready"
    if ready:
        from provisa.api.demo_templates import _replica_progress

        rt = await ensure_org_runtime(demo.template_org)
        landed, failed, declared = await _replica_progress(rt)
        ready = landed >= declared and not failed
    if not ready:
        raise ApiError(
            503,
            "sandbox.demo_not_ready",
            f"The {demo.title} demo is still being prepared; try again shortly",
            demo=demo.name,
        )


async def _open_count(conn: Any) -> int:
    return int(
        (await conn.execute_core(select(func.count()).select_from(demo_sandboxes))).scalar_one()
    )


async def open_sandbox(name: str, *, kind: str, user_id: str | None = None) -> OpenedSandbox:
    """Open a sandbox of the published demo ``name``: a visitor's (``user_id`` None, minted here)
    or a named one for the signed-in ``user_id``."""
    from provisa.api.admin.orgs_router import _admin_pool

    if kind not in (VISITOR, NAMED):
        raise ValueError(f"unknown sandbox kind {kind!r}")
    if (kind == NAMED) != (user_id is not None):
        raise ValueError("a named sandbox is opened for a signed-in user, a visitor's for none")
    demo = published_demo(name)
    await _template_ready(demo)
    admin = _admin_pool()
    org_id = new_sandbox_org_id()
    person = user_id if user_id is not None else visitor_user_id(org_id)
    async with _opening:
        async with admin.acquire() as conn:
            cap = int(settings_registry.value("sandbox.max_concurrent"))
            if await _open_count(conn) >= cap:
                raise ApiError(
                    503,
                    "sandbox.at_capacity",
                    "Every demo sandbox is in use; try again shortly",
                    limit=cap,
                )
            await conn.execute_core(
                orgs.insert().values(
                    id=org_id,
                    name=f"{demo.title} sandbox",
                    created_by=person,
                    provisioning_state="provisioning",
                    seeded_demo=False,
                )
            )
            await conn.execute_core(
                insert(demo_sandboxes).values(
                    org_id=org_id, demo=demo.name, kind=kind, user_id=person
                )
            )
    try:
        token = await _build(demo, org_id, person, kind)
    except BaseException:
        log.exception("demo sandbox %s of %s could not be opened; removing it", org_id, demo.name)
        await reap(org_id)
        raise
    log.info("demo sandbox %s of %s opened (%s)", org_id, demo.name, kind)
    return OpenedSandbox(org_id=org_id, demo=demo.name, user_id=person, token=token)


async def _build(demo: PublishedDemo, org_id: str, person: str, kind: str) -> str | None:
    from provisa.api.admin.orgs_router import _admin_pool, _pool, _refresh_root_registry_view
    from provisa.api.app import _stop_org_servers, build_org_runtime, state
    from provisa.auth.pat import PersonalAccessTokenStore
    from provisa.core import org_files
    from provisa.core.env_copy import clone_model
    from provisa.core.env_classes import COPIED
    from provisa.core.env_repo import ensure_repo, write_through
    from provisa.core.env_store import ensure_prod
    from provisa.core.environments import PROD, org_schema
    from provisa.core.org_membership import JOINED_VIA_ADMIN, grant_membership, grant_org_role
    from provisa.core.org_provisioning import provision_org
    from provisa.core.redis_location import redis_url
    from provisa.security.rights import DEPLOYMENT_GRANTER

    schema_sql = (Path(__file__).parent.parent / "core" / "schema.sql").read_text()
    await provision_org(
        _pool(),
        schema_sql,
        org_id=org_id,
        redis_url=redis_url(),
        redis_password=settings_registry.value("cache.redis_org_password"),
    )
    await ensure_prod(_admin_pool(), org_id, person)
    # The template's model, then its landed replicas -- both before the sandbox's runtime is built,
    # so its first build finds every replica already recorded as built for its own store and asks
    # for none.
    await clone_model(_pool(), org_schema(demo.template_org), org_schema(org_id), landing=COPIED)
    await org_files.prepare(org_id, state.admin_db, _stop_org_servers)
    await _copy_replicas(demo.template_org, org_id)

    rt = await state.org_registry.rebuild(org_id, lambda oid: build_org_runtime(oid))
    assert rt.model_db is not None
    if kind == VISITOR:
        async with _admin_pool().acquire() as conn:
            await conn.execute_core(
                insert(user_profiles).values(
                    user_id=person, display_name="Demo visitor", provider="sandbox"
                )
            )
    await grant_membership(_admin_pool(), person, org_id, joined_via=JOINED_VIA_ADMIN)
    await grant_org_role(rt.model_db, person, SANDBOX_ROLE, granter_capabilities=DEPLOYMENT_GRANTER)
    ensure_repo(org_id)
    async with rt.model_db.acquire() as conn:
        await write_through(
            conn, _admin_pool(), org_id, PROD, org_schema(org_id), "opened from its demo", person
        )
    await _refresh_root_registry_view()
    async with _admin_pool().acquire() as conn:
        await conn.execute_core(
            update(orgs)
            .where(orgs.c.id == org_id)
            .values(provisioning_state="ready", provisioning_error=None)
        )
    if kind != VISITOR:
        return None
    secret, _row = await PersonalAccessTokenStore(_admin_pool()).issue(
        user_id=person, org_id=org_id, name=_TOKEN_NAME, role_id=SANDBOX_ROLE
    )
    return secret


def _store_identity(org_id: str) -> str:
    """What a replica built into ``org_id``'s embedded store records as its store
    (replica_builds.store_identity, for the sandbox's own engine)."""
    from provisa.federation.engine import embedded_store_dsn

    return hashlib.sha256(f"duckdb|{embedded_store_dsn(org_id)}".encode()).hexdigest()[:32]


async def _copy_replicas(template_org: str, org_id: str) -> None:
    """The template's landed replicas, into the sandbox's own store and its own record."""
    from provisa.api.admin.orgs_router import _pool
    from provisa.core import process_region
    from provisa.core.environments import org_schema
    from provisa.core.regions import DEFAULT_REGION
    from provisa.core.schema_org import replica_state
    from provisa.federation.engine import embedded_store_dsn
    from provisa.federation.materialize_broker import copy_schema
    from provisa.federation.replica_address import REPLICAS_SUFFIX

    if process_region.region() != DEFAULT_REGION:
        # A region keeps its replicas' record in a store of its own (REQ-1922); the sandbox tier
        # runs where there are no platform regions.
        raise RuntimeError("demo sandboxes run on a deployment without platform regions")
    template_store = embedded_store_dsn(template_org).removeprefix("duckdb:///")
    store = embedded_store_dsn(org_id).removeprefix("duckdb:///")
    await asyncio.to_thread(
        copy_schema,
        template_store,
        org_schema(template_org, None, REPLICAS_SUFFIX),
        store,
        org_schema(org_id, None, REPLICAS_SUFFIX),
    )
    source = replica_state.to_metadata(_scoped_md(org_schema(template_org)))
    target = replica_state.to_metadata(_scoped_md(org_schema(org_id)))
    built = _store_identity(org_id)
    async with _pool().acquire() as conn, conn.transaction():
        rows = [
            dict(r._mapping)
            for r in (
                await conn.execute_core(select(source).where(source.c.completed_at.is_not(None)))
            ).fetchall()
        ]
        for row in rows:
            row.update(
                built_store=built,
                build_state="idle",
                build_holder=None,
                build_started_at=None,
                requested_at=None,
                requested_reason=None,
                build_wait=None,
                build_progress=None,
            )
        if rows:
            await conn.execute_core_many(insert(target), rows)


def _scoped_md(schema: str) -> Any:
    from sqlalchemy import MetaData

    return MetaData(schema=schema)


_touched: dict[str, float] = {}
_TOUCH_EVERY_S = 60.0


async def touch(org_id: str) -> None:
    """A request reached the sandbox ``org_id``: its idle expiry starts again (REQ-1600). Written
    at most once a minute per sandbox, so a busy sandbox does not write the control plane on every
    request; a minute is nothing against an expiry of ``sandbox.idle_ttl``."""
    import time

    from provisa.api.admin.orgs_router import _admin_pool

    clock = time.monotonic()
    if clock - _touched.get(org_id, float("-inf")) < _TOUCH_EVERY_S:
        return
    _touched[org_id] = clock
    async with _admin_pool().acquire() as conn:
        await conn.execute_core(
            update(demo_sandboxes)
            .where(demo_sandboxes.c.org_id == org_id)
            .values(last_active_at=datetime.now(UTC))
        )


async def expired(now: datetime | None = None) -> list[str]:
    """The sandboxes no request has reached for ``sandbox.idle_ttl`` seconds, oldest first."""
    from provisa.api.admin.orgs_router import _admin_pool

    at = now if now is not None else datetime.now(UTC)
    idle = timedelta(seconds=int(settings_registry.value("sandbox.idle_ttl")))
    async with _admin_pool().acquire() as conn:
        rows = (
            await conn.execute_core(
                select(demo_sandboxes.c.org_id)
                .where(demo_sandboxes.c.last_active_at <= at - idle)
                .order_by(demo_sandboxes.c.last_active_at)
            )
        ).fetchall()
    return [r[0] for r in rows]


async def reap(org_id: str) -> None:
    """Delete the sandbox ``org_id`` whole: its org (schemas, rows, its visitor's token), its
    engine, and its folder with its DuckDB file and uploads."""
    from provisa.api.admin.orgs_router import _admin_pool, destroy_org
    from provisa.core import org_files

    async with _admin_pool().acquire() as conn:
        row = (
            await conn.execute_core(
                select(demo_sandboxes.c.kind, demo_sandboxes.c.user_id).where(
                    demo_sandboxes.c.org_id == org_id
                )
            )
        ).fetchone()
    await destroy_org(org_id)
    if row is not None and row[0] == VISITOR:
        async with _admin_pool().acquire() as conn:
            await conn.execute_core(delete(user_profiles).where(user_profiles.c.user_id == row[1]))
    _touched.pop(org_id, None)
    folder = org_files.folder(org_id)
    if folder.exists():
        await asyncio.to_thread(shutil.rmtree, folder)
    log.info("demo sandbox %s reaped", org_id)


async def reap_expired() -> list[str]:
    """Reap every sandbox past its idle expiry; the ones reaped."""
    reaped = []
    for org_id in await expired():
        await reap(org_id)
        reaped.append(org_id)
    return reaped
