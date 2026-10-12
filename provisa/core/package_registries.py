# Copyright (c) 2026 Kenneth Stott
# Canary: 23a55676-11ae-482c-bfb3-76e53b04ac31
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The package registries an organisation's Node installs go through (REQ-1984).

An organisation setting, entered by its administrator and used by every Node install of the
organisation, for a source's own code and for its dependencies:

- npm registries, each with an address (its URL), an optional scope and a credential. One may be
  the mirror every install goes through.
- Git hosts, each with a host and a credential (an HTTPS token).

Every field holds what was entered -- the value, or a ``${secret:NAME}`` / ``${env:NAME}``
reference the administrator typed -- and is resolved at use (:func:`resolved`), in the
organisation's own vault. Nothing here writes to a vault or makes up a secret's name. The public
npm registry needs no entry.

An organisation reads and writes only its own: every call names the organisation.
"""

# Requirements: REQ-1984
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from provisa.core import secrets_store
from provisa.core.schema_admin import org_package_registries as _t

if TYPE_CHECKING:
    from provisa.core.database import Database

NPM = "npm"
GIT = "git"
KINDS = (NPM, GIT)


class PackageRegistryRefused(ValueError):
    """A registry entry that cannot be kept, or that cannot be used as entered."""

    def __init__(self, code: str, message: str, *, status: int = 400, **params: str) -> None:
        super().__init__(message)
        self.code = f"package_registry.{code}"
        self.status = status
        self.params = params


@dataclass(frozen=True)
class Registry:
    """One entry, each field as its administrator entered it."""

    id: str
    kind: str
    #: An npm registry's URL, or a Git host.
    address: str
    #: An npm registry's scope ("@acme"), or None.
    scope: str | None
    credential: str
    #: Whether this npm registry is the mirror every install goes through.
    mirror: bool


def _row(row) -> Registry:
    return Registry(row.id, row.kind, row.address, row.scope, row.credential, bool(row.mirror))


async def entries(admin_db: "Database", org_id: str) -> list[Registry]:
    """Every entry of ``org_id``: npm registries first, then Git hosts, each by address."""
    async with admin_db.acquire() as conn:
        rows = (
            await conn.execute_core(
                select(_t).where(_t.c.org_id == org_id).order_by(_t.c.kind.desc(), _t.c.address)
            )
        ).fetchall()
    return [_row(r) for r in rows]


async def read(admin_db: "Database", org_id: str, registry_id: str) -> Registry | None:
    async with admin_db.acquire() as conn:
        row = (
            await conn.execute_core(select(_t).where(_t.c.org_id == org_id, _t.c.id == registry_id))
        ).fetchone()
    return None if row is None else _row(row)


async def put(
    admin_db: "Database",
    org_id: str,
    *,
    registry_id: str | None,
    kind: str,
    address: str,
    scope: str | None,
    credential: str | None,
    mirror: bool,
    actor: str | None,
) -> Registry:
    """Keep an entry of ``org_id``: a new one when ``registry_id`` is None, else the one it
    names, replaced. Each field is kept exactly as entered. ``credential`` None keeps the one the
    entry already holds, which there must then be.

    Refused by name: an unknown kind; an empty address or credential; a scope or the mirror on a
    Git host; a second mirror; a scope another npm registry has; a host another Git host entry
    has."""
    if kind not in KINDS:
        raise PackageRegistryRefused(
            "unknown_kind", f"{kind!r} is not a kind of package registry", kind=kind
        )
    address = address.strip()
    scope = (scope or "").strip() or None
    credential = (credential or "").strip() or None
    if kind == GIT and scope is not None:
        raise PackageRegistryRefused("git_scope", "A Git host has no scope", address=address)
    if kind == GIT and mirror:
        raise PackageRegistryRefused(
            "git_mirror", "Only an npm registry can be the mirror", address=address
        )
    held = None
    if registry_id is not None:
        held = await read(admin_db, org_id, registry_id)
        if held is None:
            raise PackageRegistryRefused(
                "not_found",
                f"There is no package registry {registry_id!r}",
                status=404,
                registry=registry_id,
            )
        if held.kind != kind:
            raise PackageRegistryRefused(
                "kind_changed",
                "An entry's kind cannot change; remove it and add a new one",
                registry=registry_id,
            )
        credential = credential or held.credential
    missing = [
        name for name, value in (("address", address), ("credential", credential)) if not value
    ]
    if missing:
        raise PackageRegistryRefused(
            "incomplete", f"A {kind} entry needs {', '.join(missing)}", missing=", ".join(missing)
        )
    others = [e for e in await entries(admin_db, org_id) if e.id != registry_id]
    if mirror and any(e.mirror for e in others):
        (current,) = [e for e in others if e.mirror]
        raise PackageRegistryRefused(
            "second_mirror",
            f"{current.address} is already the mirror; an organisation has one",
            mirror=current.address,
        )
    if (
        kind == NPM
        and scope is not None
        and any(e.kind == NPM and e.scope == scope for e in others)
    ):
        raise PackageRegistryRefused(
            "scope_taken", f"Another npm registry already has the scope {scope}", scope=scope
        )
    if kind == GIT and any(e.kind == GIT and e.address == address for e in others):
        raise PackageRegistryRefused(
            "host_taken", f"The Git host {address} is already entered", address=address
        )
    values = {
        "org_id": org_id,
        "id": registry_id or uuid.uuid4().hex,
        "kind": kind,
        "address": address,
        "scope": scope,
        "credential": credential,
        "mirror": mirror,
        "updated_by": actor,
    }
    async with admin_db.acquire() as conn:
        await conn.upsert(
            _t,
            values,
            index_elements=["org_id", "id"],
            update_columns=["address", "scope", "credential", "mirror", "updated_by"],
            set_extra={"updated_at": func.now()},
        )
    kept = await read(admin_db, org_id, values["id"])
    if kept is None:
        raise RuntimeError(
            f"package registry {values['id']} was kept for {org_id} but cannot be read back"
        )
    return kept


async def forget(admin_db: "Database", org_id: str, registry_id: str) -> bool:
    """Remove an entry of ``org_id``: True when there was one. A secret its fields named is the
    administrator's and is left as it is."""
    async with admin_db.acquire() as conn:
        result = await conn.execute_core(
            delete(_t).where(_t.c.org_id == org_id, _t.c.id == registry_id)
        )
    return result.rowcount > 0


@dataclass(frozen=True)
class Resolved:
    """An entry ready for an install: every field resolved."""

    id: str
    kind: str
    address: str
    scope: str | None
    credential: str
    mirror: bool


async def resolved(admin_db: "Database", org_id: str) -> list[Resolved]:
    """Every entry of ``org_id`` with each field resolved by the product's one resolver
    (``core.secrets.resolve_secrets``) in THAT organisation's vault, bound here for this read
    alone. Refused by the entry's address and the field's name when a field cannot be resolved;
    the reason is the resolver's, which names only a reference the administrator typed."""
    from provisa.core.secrets import resolve_secrets

    kept = await entries(admin_db, org_id)
    out: list[Resolved] = []
    async with secrets_store.bound(admin_db, org_id):
        for entry in kept:
            fields: dict[str, str | None] = {}
            for name in ("address", "scope", "credential"):
                value = getattr(entry, name)
                if value is None:
                    fields[name] = None
                    continue
                try:
                    fields[name] = resolve_secrets(value)
                except (KeyError, ValueError) as unresolved:
                    reason = unresolved.args[0] if unresolved.args else type(unresolved).__name__
                    raise PackageRegistryRefused(
                        "unresolved",
                        f"The {name} of package registry {entry.address} could not be resolved: "
                        f"{reason}",
                        registry=entry.id,
                        field=name,
                        reason=str(reason),
                    ) from None
            address, credential = fields["address"], fields["credential"]
            assert address is not None and credential is not None  # NOT NULL columns
            out.append(
                Resolved(entry.id, entry.kind, address, fields["scope"], credential, entry.mirror)
            )
    return out
