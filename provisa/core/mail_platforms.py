# Copyright (c) 2026 Kenneth Stott
# Canary: ce34215e-bd2d-4773-a1b0-d7a8cbdee25b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The mail platforms an organisation's sources sign in to (REQ-1923).

A source that reads a person's mail is signed in by that person's approval of a client the
ORGANISATION registered with the platform (Google Workspace, Microsoft 365). The client is the
organisation's: its administrator enters it once, and every source of the organisation uses it.
Nobody adding a source sees or types it.

What is kept, per organisation and platform: the client's id and what else the platform's
addresses depend on (Microsoft's tenant) in ``org_mail_platforms``; the client's secret in the
organisation's vault under :func:`secret_name`. An organisation reads and writes only its own:
every call here names the organisation, and nothing looks one up across them.

A platform is one a source kind has declared (:func:`declare`), with the settings it takes
beside the client. A setting it does not take is refused by name.
"""

# Requirements: REQ-1923
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from provisa.core import secrets_store
from provisa.core.schema_admin import org_mail_platforms

if TYPE_CHECKING:
    from provisa.core.database import Database


class MailPlatformRefused(ValueError):
    """A mail platform's settings that cannot be kept, or that are not there to use."""

    def __init__(self, code: str, message: str, *, status: int = 400, **params: str) -> None:
        super().__init__(message)
        self.code = f"mail_platform.{code}"
        self.status = status
        self.params = params


@dataclass(frozen=True)
class Platform:
    """A mail platform sources sign in to: its id (the source type that reads it) and the
    settings its client is entered with beside the id and secret."""

    id: str
    settings: tuple[str, ...] = ()
    #: What the platform is entered with, beside the client, for sources that read the
    #: ORGANISATION's mailboxes: needed once the administrator allows such sources.
    organisation_settings: tuple[str, ...] = ()
    #: Whether those sources read with a credential of the platform's own, entered as a secret
    #: (Google: a service account's key), and not with the client's.
    organisation_key: bool = False
    #: What the administrator authorises at the platform for that credential, to copy from the
    #: admin section (Google: the scopes of its domain-wide delegation line). Not secret.
    organisation_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Configured:
    """An organisation's entry for one platform, each credential as its administrator entered
    it: the value itself, or a ``${secret:NAME}`` / ``${env:NAME}`` reference they typed. It is
    resolved where it is used (:func:`resolved`); nothing here names or keeps a secret of its
    own making."""

    platform: str
    #: None where the organisation entered no client: its sources read the organisation's
    #: mailboxes with the platform's own credential, and nobody signs in.
    client_id: str | None
    settings: dict[str, str] = field(default_factory=dict)
    #: Whether the administrator allows sources that read the organisation's mailboxes with
    #: this client's own credential.
    organisation_mailboxes: bool = False
    #: The organisation's own credential for its mailboxes, as entered, where the platform has
    #: one and one was entered; None otherwise.
    organisation_key: str | None = None
    #: The client's secret, as entered; None where the entry holds no client.
    client_secret: str | None = None

    @property
    def client(self) -> str:
        """The client's id, refused by name where the entry holds no client."""
        if self.client_id is None:
            raise _not_configured(self.platform)
        return self.client_id


_PLATFORMS: dict[str, Platform] = {}


def declare(platform: Platform) -> None:
    _PLATFORMS[platform.id] = platform


def platforms() -> list[Platform]:
    """Every platform a source kind has declared, in the order declared."""
    return list(_PLATFORMS.values())


def source_types() -> frozenset[str]:
    """The source kinds that are mail platforms. Each declares itself where it is defined, so
    they are loaded here before they are counted."""
    import provisa.google_workspace  # noqa: F401  (declares the Google Workspace platform)
    import provisa.microsoft365  # noqa: F401  (declares the Microsoft 365 platform)

    return frozenset(_PLATFORMS)


def platform(platform_id: str) -> Platform:
    if platform_id not in _PLATFORMS:
        raise MailPlatformRefused(
            "unknown", f"No mail platform {platform_id!r} exists", status=404, platform=platform_id
        )
    return _PLATFORMS[platform_id]


#: The credentials an entry holds, by the name the form gives each field.
CLIENT_SECRET = "client_secret"
ORGANISATION_KEY = "organisation_key"


async def resolved(
    admin_db: "Database", org_id: str, platform_id: str, field: str, value: str | None
) -> str:
    """``org_id``'s ``field`` of its ``platform_id`` entry, ready to use: ``value`` as the
    administrator entered it, with a ``${secret:NAME}`` / ``${env:NAME}`` reference they typed
    resolved by the product's one resolver (``core.secrets.resolve_secrets``) -- IN THAT
    ORGANISATION'S vault. A value that is no reference is used as it is.

    The vault is bound here, for this read alone, and never taken from the caller: a reader of a
    mail source is reached from a replica build, a check for changes and a preview, and those
    bind a vault only for a source whose own fields name a secret -- a source of the
    organisation's mailboxes names none. A caller's own binding, whoever's it is, is put back
    when the read ends, so an entry is never resolved in another organisation's vault.

    Refused by the field's name when nothing was entered for it, or when what was entered
    cannot be resolved; the reason is the resolver's own."""
    from provisa.core.secrets import resolve_secrets

    if not value:
        raise _not_configured(platform_id)
    try:
        async with secrets_store.bound(admin_db, org_id):
            return resolve_secrets(value)
    except (KeyError, ValueError) as unresolved:
        reason = unresolved.args[0] if unresolved.args else type(unresolved).__name__
        raise MailPlatformRefused(
            "credential_unresolved",
            f"The {platform_id} {field} could not be resolved: {reason}",
            platform=platform_id,
            field=field,
            reason=str(reason),
        ) from None


async def read(admin_db: "Database", org_id: str, platform_id: str) -> Configured | None:
    """``org_id``'s client for the platform, or None when it has entered none."""
    platform(platform_id)
    async with admin_db.acquire() as conn:
        row = (
            await conn.execute_core(
                select(
                    org_mail_platforms.c.client_id,
                    org_mail_platforms.c.settings,
                    org_mail_platforms.c.organisation_mailboxes,
                    org_mail_platforms.c.organisation_key,
                    org_mail_platforms.c.client_secret,
                ).where(
                    org_mail_platforms.c.org_id == org_id,
                    org_mail_platforms.c.platform == platform_id,
                )
            )
        ).fetchone()
    if row is None:
        return None
    return Configured(platform_id, row[0], json.loads(row[1]), bool(row[2]), row[3], row[4])


async def require(admin_db: "Database", org_id: str, platform_id: str) -> Configured:
    """``org_id``'s client for the platform, refused by name when it has entered none."""
    configured = await read(admin_db, org_id, platform_id)
    if configured is None or configured.client_id is None:
        raise _not_configured(platform_id)
    return configured


def _not_configured(platform_id: str) -> MailPlatformRefused:
    return MailPlatformRefused(
        "not_configured",
        f"This organisation has not connected {platform_id} yet; an administrator enters "
        "its client once, under Admin > Email.",
        platform=platform_id,
    )


async def require_organisation(admin_db: "Database", org_id: str, platform_id: str) -> Configured:
    """``org_id``'s entry for the platform, for a source that reads the ORGANISATION's
    mailboxes with the platform's own credential: refused by name when the organisation has
    entered nothing, and when its administrator has not allowed such sources. An entry that
    allows them holds what they read with (:func:`put`), which need not be a client."""
    configured = await read(admin_db, org_id, platform_id)
    if configured is None:
        raise _not_configured(platform_id)
    if not configured.organisation_mailboxes:
        raise MailPlatformRefused(
            "organisation_mailboxes_off",
            f"This organisation has not allowed sources that read its mailboxes for "
            f"{platform_id}; an administrator turns it on under Admin > Email.",
            status=403,
            platform=platform_id,
        )
    return configured


async def put(
    admin_db: "Database",
    org_id: str,
    platform_id: str,
    *,
    client_id: str,
    client_secret: str | None,
    settings: dict[str, str],
    actor: str | None,
    organisation_mailboxes: bool,
    organisation_key: str | None = None,
) -> Configured:
    """Keep ``org_id``'s client for the platform. Each credential is kept exactly as entered --
    the value, or a reference the administrator typed -- in the entry's own row; nothing is
    written to a vault and no name is made up for it. ``client_secret`` None keeps the one the
    entry already holds, which there must then be: a client is never kept without its secret. A
    platform that reads the organisation's mailboxes with a credential of its own may be kept
    with no client at all once such sources are allowed; a sign-in then refuses by name.
    ``organisation_mailboxes`` is stated at every save: whether sources may read the
    organisation's mailboxes with the platform's own credential. ``organisation_key`` is that
    credential where the platform has one of its own (None keeps the one already entered); once
    such sources are allowed, it and the platform's organisation settings must be there."""
    declared = platform(platform_id)
    client_id = client_id.strip()
    settings = {key: value.strip() for key, value in settings.items()}
    unknown = sorted(set(settings) - set(declared.settings) - set(declared.organisation_settings))
    if organisation_key and not declared.organisation_key:
        unknown.append("organisation_key")
    if unknown:
        raise MailPlatformRefused(
            "unknown_setting",
            f"{', '.join(unknown)} is not a setting of {platform_id}",
            setting=", ".join(unknown),
        )
    missing = [key for key in declared.settings if not settings.get(key)]
    # No client at all: only where the platform's own credential reads the mailboxes, and only
    # with such sources allowed -- an entry is never kept that nothing can read with.
    no_client = (
        declared.organisation_key and organisation_mailboxes and not client_id and not client_secret
    )
    if not client_id and not no_client:
        missing.insert(0, "client_id")
    held = await read(admin_db, org_id, platform_id)
    # What is not entered again is what the entry already holds.
    client_secret = client_secret or (None if held is None else held.client_secret)
    if declared.organisation_key:
        organisation_key = organisation_key or (None if held is None else held.organisation_key)
    if not no_client and not client_secret:
        missing.append("client_secret")
    if organisation_mailboxes:
        missing += [key for key in declared.organisation_settings if not settings.get(key)]
        if declared.organisation_key and not organisation_key:
            missing.append("organisation_key")
    if missing:
        raise MailPlatformRefused(
            "incomplete", f"{platform_id} needs {', '.join(missing)}", missing=", ".join(missing)
        )
    values = {
        "org_id": org_id,
        "platform": platform_id,
        "client_id": None if no_client else client_id,
        "client_secret": None if no_client else client_secret,
        "settings": json.dumps(settings, sort_keys=True),
        "organisation_mailboxes": organisation_mailboxes,
        "organisation_key": organisation_key if declared.organisation_key else None,
        "updated_by": actor,
    }
    async with admin_db.acquire() as conn:
        await conn.upsert(
            org_mail_platforms,
            values,
            index_elements=["org_id", "platform"],
            update_columns=[
                "client_id",
                "client_secret",
                "settings",
                "organisation_mailboxes",
                "organisation_key",
                "updated_by",
            ],
            set_extra={"updated_at": func.now()},
        )
    kept = await read(admin_db, org_id, platform_id)
    if kept is None:
        raise RuntimeError(f"{platform_id} was kept for {org_id} but cannot be read back")
    return kept


async def forget(admin_db: "Database", org_id: str, platform_id: str) -> bool:
    """Remove ``org_id``'s entry for the platform: True when there was one. Its credentials go
    with its row; a secret the administrator named in it is theirs and is left as it is."""
    platform(platform_id)
    async with admin_db.acquire() as conn:
        result = await conn.execute_core(
            delete(org_mail_platforms).where(
                org_mail_platforms.c.org_id == org_id,
                org_mail_platforms.c.platform == platform_id,
            )
        )
    return result.rowcount > 0
