# Copyright (c) 2026 Kenneth Stott
# Canary: 34f35188-6109-433a-986c-10cd13df94c2
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a Microsoft 365 source is set up with (REQ-1923): its mapping, read here and nowhere
else -- when the source is saved, when a person connects it, and when its mail is fetched.

A source reads one mailbox with its owner's approval of the organisation's Microsoft client
(``provisa.core.mail_platforms``). It keeps the mailbox's address, what it reads, and the
reference that names the refresh token the approval produced in the organisation's vault.
"""

# Requirements: REQ-1923
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MAIL, CALENDAR, TASKS = "mail", "calendar", "tasks"
#: What a source can read: mail, and calendars and To Do tasks, read and written (REQ-1994).
RESOURCES: tuple[str, ...] = (MAIL, CALENDAR, TASKS)

LOGIN = "https://login.microsoftonline.com"
_GRAPH = "https://graph.microsoft.com/"
#: What Microsoft is asked for, by what the source reads: mail read-only; calendars and tasks
#: read and written (REQ-1994).
RESOURCE_SCOPES: dict[str, str] = {
    MAIL: f"{_GRAPH}Mail.Read",
    CALENDAR: f"{_GRAPH}Calendars.ReadWrite",
    TASKS: f"{_GRAPH}Tasks.ReadWrite",
}
#: Asked for by every source: a refresh token, and the name of the account that approved.
BASE_SCOPES: tuple[str, ...] = ("offline_access", f"{_GRAPH}User.Read")

#: The mapping keys that hold a credential, kept as references into the vault.
SECRET_KEYS: tuple[str, ...] = ("refresh_token",)
#: REQ-1994: whether a write Graph announces to an event's attendees is made at all (Graph has
#: no way to make one without telling them); and how many days either side of today a check for
#: changes looks at a calendar's events.
SEND_UPDATES = "calendar_send_updates"
CHECK_DAYS = "calendar_check_days"
_KEYS = frozenset(
    {"accounts", "resources", "refresh_token", "mailboxes", "mail_since", SEND_UPDATES, CHECK_DAYS}
)
#: What the organisation's own credential is asked for (the client-credentials grant): every
#: permission an administrator consented to for the application.
ORGANISATION_SCOPE = f"{_GRAPH}.default"
EVERYONE, GROUP, LIST = "everyone", "group", "list"
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# A directory is named by its id (a GUID) or by one of its domains.
_TENANT = re.compile(
    r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    r"|[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"
)


class InvalidMicrosoft365Source(ValueError):
    """The settings cannot be a Microsoft 365 source; the message says which and why."""


@dataclass(frozen=True)
class Mailboxes:
    """Which mailboxes a source of the organisation's reads: everyone in the directory, the
    members of a group (named by its id or its address), or the addresses listed."""

    kind: str  # EVERYONE | GROUP | LIST
    group: str | None = None
    addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    """A source is one of two shapes: one mailbox its owner connected (``account`` and
    ``refresh_token``), or the organisation's mailboxes read with the organisation's own
    credential (``mailboxes``)."""

    resources: tuple[str, ...]
    account: str | None = None  # the mailbox's address
    #: Only on a source connected before approvals were kept in the state store: the
    #: reference that named its owner's approval. None on every source connected since.
    refresh_token: str | None = None
    mailboxes: Mailboxes | None = None
    #: Nothing received before this date is held (``mail_since``); None: mail of any age.
    since: dt.date | None = None
    #: REQ-1994: a write Graph would announce to attendees is made only when this is on.
    send_updates: bool = False
    #: REQ-1994: days either side of today the check for changes looks at; None when the source
    #: does not read calendars.
    check_days: int | None = None

    @property
    def organisation(self) -> bool:
        return self.mailboxes is not None

    def scopes(self) -> list[str]:
        return scopes(self.resources)


def scopes(resources: tuple[str, ...] | list[str]) -> list[str]:
    """What Microsoft is asked for to read ``resources``, and nothing else."""
    return [*(RESOURCE_SCOPES[r] for r in resources), *BASE_SCOPES]


def tenant_path(tenant: str | None) -> str:
    """``tenant`` as it goes into Microsoft's sign-in addresses, or a refusal: only a directory
    id or domain is put into an address."""
    stated = (tenant or "").strip()
    if not _TENANT.fullmatch(stated):
        raise InvalidMicrosoft365Source(
            "the organisation's Microsoft 365 setting names no directory (tenant): it is the "
            "directory's ID or its domain"
        )
    return stated


def authorization_url(tenant: str | None) -> str:
    return f"{LOGIN}/{tenant_path(tenant)}/oauth2/v2.0/authorize"


def token_url(tenant: str | None) -> str:
    return f"{LOGIN}/{tenant_path(tenant)}/oauth2/v2.0/token"


def _resources(mapping: dict) -> tuple[str, ...]:
    resources = mapping.get("resources")
    if not isinstance(resources, list) or not resources:
        raise InvalidMicrosoft365Source(f"resources must say what is read: {', '.join(RESOURCES)}")
    unread = [r for r in resources if r not in RESOURCES]
    if unread:
        raise InvalidMicrosoft365Source(
            f"cannot read {', '.join(map(str, unread))}; a source reads {', '.join(RESOURCES)}"
        )
    return tuple(resources)


def _address(value: object) -> str:
    address = value.strip() if isinstance(value, str) else ""
    if not _ADDRESS.fullmatch(address):
        raise InvalidMicrosoft365Source(f"{value!r} is not a mailbox address")
    return address


def _mailboxes(stated: object) -> Mailboxes:
    """Which of the organisation's mailboxes: exactly one of everyone, a group, a list."""
    if not isinstance(stated, dict) or len(stated) != 1:
        raise InvalidMicrosoft365Source(
            "mailboxes must say one of: everyone, a group, or a list of addresses"
        )
    ((kind, value),) = stated.items()
    if kind == EVERYONE:
        if value is not True:
            raise InvalidMicrosoft365Source("mailboxes.everyone is stated as true or left out")
        return Mailboxes(EVERYONE)
    if kind == GROUP:
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "'/\\ "):
            raise InvalidMicrosoft365Source(
                "mailboxes.group names one group, by its ID or its address"
            )
        return Mailboxes(GROUP, group=value.strip())
    if kind == LIST:
        if not isinstance(value, list) or not value:
            raise InvalidMicrosoft365Source("mailboxes.list names at least one address")
        addresses = tuple(dict.fromkeys(_address(a).lower() for a in value))
        return Mailboxes(LIST, addresses=addresses)
    raise InvalidMicrosoft365Source(
        f"mailboxes.{kind} is not a way to choose mailboxes: everyone, group or list"
    )


def _since(mapping: dict) -> dt.date | None:
    """``mail_since``: the date before which nothing received is held, as YYYY-MM-DD; None
    where the source states none. Stated and validated as a Google Workspace source's is."""
    stated = mapping.get("mail_since")
    if stated is None or (isinstance(stated, str) and not stated.strip()):
        return None
    if not isinstance(stated, str):
        raise InvalidMicrosoft365Source(f"mail_since must be a date as YYYY-MM-DD, not {stated!r}")
    try:
        return dt.date.fromisoformat(stated.strip())
    except ValueError:
        raise InvalidMicrosoft365Source(
            f"mail_since must be a date as YYYY-MM-DD, not {stated!r}"
        ) from None


def parse(mapping: dict) -> Settings:
    """The settings ``mapping`` states, or a refusal naming what is wrong with it."""
    unknown = sorted(set(mapping) - _KEYS)
    if unknown:
        raise InvalidMicrosoft365Source(f"unknown setting(s): {', '.join(unknown)}")
    if "mailboxes" in mapping:
        own = sorted({"accounts", "refresh_token"} & set(mapping))
        if own:
            raise InvalidMicrosoft365Source(
                f"a source of the organisation's mailboxes states no {' or '.join(own)}: "
                "nobody connects it"
            )
        resources = _resources(mapping)
        return Settings(
            resources,
            mailboxes=_mailboxes(mapping["mailboxes"]),
            since=_since(mapping),
            **_calendar(mapping, resources),
        )
    accounts = mapping.get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 1 or not isinstance(accounts[0], str):
        raise InvalidMicrosoft365Source("accounts must name one mailbox, by its address")
    account = _address(accounts[0])
    resources = _resources(mapping)
    # The owner's approval is sign-in state, kept in the organisation's state store, and is no
    # setting of the source. A source connected before that holds a reference to it here, which
    # its reader takes once (``api_source.oauth_store``); nothing else reads this key.
    token = mapping.get("refresh_token")
    if token is not None and not isinstance(token, str):
        raise InvalidMicrosoft365Source("refresh_token, where a source still has one, is text")
    return Settings(
        resources,
        account=account,
        refresh_token=(token or "").strip() or None,
        since=_since(mapping),
        **_calendar(mapping, resources),
    )


def _calendar(mapping: dict, resources: tuple[str, ...]) -> dict:
    """The calendar settings (REQ-1994). ``calendar_check_days`` is stated by a source that
    reads calendars (the source form supplies it); ``calendar_send_updates`` unstated is off: a
    write tells nobody."""
    if CALENDAR not in resources:
        stated = [key for key in (SEND_UPDATES, CHECK_DAYS) if key in mapping]
        if stated:
            raise InvalidMicrosoft365Source(
                f"{', '.join(stated)} is a setting of calendars, which this source does not read"
            )
        return {}
    days = mapping.get(CHECK_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise InvalidMicrosoft365Source(
            f"{CHECK_DAYS} must be a whole number of days, 1 or more, got {days!r}"
        )
    send = mapping.get(SEND_UPDATES, False)
    if not isinstance(send, bool):
        raise InvalidMicrosoft365Source(f"{SEND_UPDATES} must be true or false")
    return {"send_updates": send, "check_days": days}
