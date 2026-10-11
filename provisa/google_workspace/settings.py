# Copyright (c) 2026 Kenneth Stott
# Canary: 095f3c21-cc49-4ddb-bb8e-07a0b655d5cb
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a Google Workspace source is set up with (REQ-1923).

One source reads the resources its operator ticks -- mail, calendar, tasks -- and asks Google
only for the scope of a ticked resource. A source is one of two shapes:

- one mailbox its owner connected: the address, and the reference that names the refresh
  token the owner's approval of the organisation's Google client produced;
- the organisation's mailboxes (``mailboxes``: everyone, the members of a group, or a list),
  read with the organisation's own credential -- a service account its Workspace domain has
  delegated to, entered once on the organisation's Google platform entry
  (``provisa.core.mail_platforms``). Such a source holds no credential at all.

Every table leads with the account it was read from, so many mailboxes are the same tables.

A setting this module does not read is refused by name, as is a combination Google refuses.
"""

# Requirements: REQ-1923
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from provisa.core.auth_models import ApiAuthOAuth2RefreshToken

if TYPE_CHECKING:
    from provisa.core.mail_platforms import Configured


#: Google's token endpoint, as its OpenID configuration document publishes it.
TOKEN_URL = "https://oauth2.googleapis.com/token"

MAIL, CALENDAR, TASKS = "mail", "calendar", "tasks"
#: The resources Google's APIs offer under one credential, in the order the setup shows them.
RESOURCES: tuple[str, ...] = (MAIL, CALENDAR, TASKS)
#: The resources this build reads. Another is refused by name until it is built.
RESOURCES_READ: frozenset[str] = frozenset({MAIL})

#: How much of a message is read. Headers and labels only is Google's gmail.metadata scope:
#: no body, and Google refuses a search under it.
MAIL_FULL, MAIL_HEADERS = "full", "headers"

_SCOPE = "https://www.googleapis.com/auth/"
MAIL_SCOPES: dict[str, str] = {
    MAIL_FULL: f"{_SCOPE}gmail.readonly",
    MAIL_HEADERS: f"{_SCOPE}gmail.metadata",
}
RESOURCE_SCOPES: dict[str, tuple[str, ...]] = {
    CALENDAR: (f"{_SCOPE}calendar.calendarlist.readonly", f"{_SCOPE}calendar.events.readonly"),
    TASKS: (f"{_SCOPE}tasks.readonly",),
}

#: How a source of one mailbox signs in: as the person who approved the organisation's client.
GOOGLE_ACCOUNT = "google_account"

#: The settings that are credentials: kept in the org's vault, the source holding a reference.
#: A source of the organisation's mailboxes has none: the service account's key is the
#: organisation's, on its platform entry.

EVERYONE, GROUP, LIST = "everyone", "group", "list"
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_MAIL_KEYS = (
    "mail_content",
    "mail_search",
    "mail_labels",
    "mail_since",
    "mail_include_spam_trash",
)
_KEYS = frozenset(
    (
        "accounts",
        "resources",
        "sign_in",
        "refresh_token",
        "mailboxes",
        *_MAIL_KEYS,
    )
)


class InvalidGoogleWorkspaceSource(ValueError):
    """A Google Workspace source's settings that cannot be a source, said in the setup's terms."""


@dataclass(frozen=True)
class MailSettings:
    """Which mail a source holds. Each narrows what Google is asked for; none is a filter a
    statement adds."""

    content: str  # MAIL_FULL | MAIL_HEADERS
    search: str | None  # as typed in Gmail's own search box
    labels: tuple[str, ...]  # by name; a message carries every one
    since: dt.date | None  # nothing received before it
    include_spam_trash: bool


@dataclass(frozen=True)
class Mailboxes:
    """Which mailboxes a source of the organisation's reads: every user of the domain, the
    members of a group (named by its address or its id), or the addresses listed."""

    kind: str  # EVERYONE | GROUP | LIST
    group: str | None = None
    addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    """A source is one of two shapes: one mailbox its owner connected (``accounts`` and
    ``refresh_token``), or the organisation's mailboxes read with the organisation's own
    credential (``mailboxes``)."""

    resources: tuple[str, ...]
    mail: MailSettings | None  # None when mail is not ticked
    accounts: tuple[str, ...] = ()  # the one mailbox's address
    #: Only on a source connected before approvals were kept in the organisation's state
    #: store: the approval as the source then held it. Taken into the state store at the
    #: source's next read (loader), and never written by a sign-in now.
    refresh_token: str | None = None
    mailboxes: Mailboxes | None = None

    @property
    def organisation(self) -> bool:
        return self.mailboxes is not None

    def scopes(self) -> list[str]:
        """What Google is asked for: the scope of each ticked resource and of no other."""
        scopes: list[str] = []
        for resource in self.resources:
            if resource == MAIL:
                assert self.mail is not None  # parse: mail ticked states its content
                scopes.append(MAIL_SCOPES[self.mail.content])
            else:
                scopes.extend(RESOURCE_SCOPES[resource])
        return scopes

    def auth(
        self, account: str, client: "Configured", refresh_token: str
    ) -> ApiAuthOAuth2RefreshToken:
        """The credential the one mailbox is read with: ``refresh_token``, its owner's approval
        of ``client`` -- the organisation's Google client, which the approval was given to and
        is renewed with. The approval is kept for the source in the organisation's state store
        and is the caller's to read; the source's settings do not hold it."""
        if self.organisation or account not in self.accounts:
            raise InvalidGoogleWorkspaceSource(f"{account} is not the mailbox of this source")
        return ApiAuthOAuth2RefreshToken(
            client_id=client.client,
            client_secret=client.client_secret,
            refresh_token=refresh_token,
            token_url=TOKEN_URL,
        )


def _text(mapping: dict, key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidGoogleWorkspaceSource(f"{key} must be text")
    return value.strip() or None


def _names(mapping: dict, key: str) -> tuple[str, ...]:
    value = mapping.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidGoogleWorkspaceSource(f"{key} must be a list of text")
    names = tuple(v.strip() for v in value if v.strip())
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise InvalidGoogleWorkspaceSource(f"{key} names {', '.join(repeated)} more than once")
    return names


def _accounts(mapping: dict) -> tuple[str, ...]:
    accounts = _names(mapping, "accounts")
    if not accounts:
        raise InvalidGoogleWorkspaceSource("Name the account to read")
    for account in accounts:
        name, at, domain = account.partition("@")
        if not (name and at and "." in domain) or " " in account or "@" in domain:
            raise InvalidGoogleWorkspaceSource(f"{account!r} is not an email address")
    if len(accounts) > 1:
        raise InvalidGoogleWorkspaceSource(
            f"A source reads one account; {len(accounts)} were named ({', '.join(accounts)})"
        )
    return accounts


def _resources(mapping: dict) -> tuple[str, ...]:
    ticked = _names(mapping, "resources")
    if not ticked:
        raise InvalidGoogleWorkspaceSource("Choose what the source reads: " + ", ".join(RESOURCES))
    unknown = [r for r in ticked if r not in RESOURCES]
    if unknown:
        raise InvalidGoogleWorkspaceSource(
            f"{', '.join(unknown)} is not something a Google Workspace source reads "
            f"({', '.join(RESOURCES)})"
        )
    unread = [r for r in ticked if r not in RESOURCES_READ]
    if unread:
        raise InvalidGoogleWorkspaceSource(f"{', '.join(unread)} is not read by this version")
    return tuple(r for r in RESOURCES if r in ticked)


def _connected(mapping: dict) -> str | None:
    """How a source of one mailbox is connected, checked; and the approval a source connected
    before approvals were kept in the state store still names here, or None. A source with no
    approval at all is refused where it is read (not connected), not here."""
    sign_in = _text(mapping, "sign_in")
    if sign_in != GOOGLE_ACCOUNT:
        raise InvalidGoogleWorkspaceSource(
            f"sign_in must be {GOOGLE_ACCOUNT}, not {sign_in!r}: a source of one mailbox is "
            "connected by its owner; the organisation's mailboxes are read by a source that "
            "states mailboxes"
        )
    return _text(mapping, "refresh_token")


def _mailboxes(stated: object) -> Mailboxes:
    """Which of the organisation's mailboxes: exactly one of everyone, a group, a list."""
    if not isinstance(stated, dict) or len(stated) != 1:
        raise InvalidGoogleWorkspaceSource(
            "mailboxes must say one of: everyone, a group, or a list of addresses"
        )
    ((kind, value),) = stated.items()
    if kind == EVERYONE:
        if value is not True:
            raise InvalidGoogleWorkspaceSource("mailboxes.everyone is stated as true or left out")
        return Mailboxes(EVERYONE)
    if kind == GROUP:
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "'/\\ "):
            raise InvalidGoogleWorkspaceSource(
                "mailboxes.group names one group, by its address or its ID"
            )
        return Mailboxes(GROUP, group=value.strip())
    if kind == LIST:
        if not isinstance(value, list) or not value:
            raise InvalidGoogleWorkspaceSource("mailboxes.list names at least one address")
        addresses = []
        for address in value:
            if not isinstance(address, str) or not _ADDRESS.fullmatch(address.strip()):
                raise InvalidGoogleWorkspaceSource(f"{address!r} is not a mailbox address")
            addresses.append(address.strip().lower())
        return Mailboxes(LIST, addresses=tuple(dict.fromkeys(addresses)))
    raise InvalidGoogleWorkspaceSource(
        f"mailboxes.{kind} is not a way to choose mailboxes: everyone, group or list"
    )


def _mail(mapping: dict) -> MailSettings:
    content = _text(mapping, "mail_content")
    if content not in MAIL_SCOPES:
        raise InvalidGoogleWorkspaceSource(
            f"mail_content must be one of {', '.join(MAIL_SCOPES)}, not {content!r}"
        )
    search = _text(mapping, "mail_search")
    since_text = _text(mapping, "mail_since")
    since: dt.date | None = None
    if since_text is not None:
        try:
            since = dt.date.fromisoformat(since_text)
        except ValueError:
            raise InvalidGoogleWorkspaceSource(
                f"mail_since must be a date as YYYY-MM-DD, not {since_text!r}"
            ) from None
    # Google: a search "cannot be used when accessing the api using the gmail.metadata scope",
    # and a date is asked for as a search.
    if content == MAIL_HEADERS and (search is not None or since is not None):
        raise InvalidGoogleWorkspaceSource(
            "Google does not search mail read as headers and labels only: leave out "
            "mail_search and mail_since, or read whole messages"
        )
    spam_trash = mapping.get("mail_include_spam_trash", False)  # Google's own default
    if not isinstance(spam_trash, bool):
        raise InvalidGoogleWorkspaceSource("mail_include_spam_trash must be true or false")
    return MailSettings(content, search, _names(mapping, "mail_labels"), since, spam_trash)


def parse(mapping: dict) -> Settings:
    """A Google Workspace source's settings, as its mapping states them."""
    unread = sorted(set(mapping) - _KEYS)
    if unread:
        raise InvalidGoogleWorkspaceSource(
            f"{', '.join(unread)} is not a setting of a Google Workspace source"
        )
    resources = _resources(mapping)
    if "mailboxes" in mapping:
        own = sorted({"accounts", "sign_in", "refresh_token"} & set(mapping))
        if own:
            raise InvalidGoogleWorkspaceSource(
                f"a source of the organisation's mailboxes states no {' or '.join(own)}: "
                "nobody connects it"
            )
        mailboxes, accounts, token = _mailboxes(mapping["mailboxes"]), (), None
    else:
        mailboxes, token, accounts = None, _connected(mapping), _accounts(mapping)
    if MAIL in resources:
        mail = _mail(mapping)
    else:
        stated = [key for key in _MAIL_KEYS if key in mapping]
        if stated:
            raise InvalidGoogleWorkspaceSource(
                f"{', '.join(stated)} is a setting of mail, which this source does not read"
            )
        mail = None
    return Settings(resources, mail, accounts, token, mailboxes)
