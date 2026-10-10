# Copyright (c) 2026 Kenneth Stott
# Canary: 20c43e0b-3f9a-41dc-a064-340e919b84e5
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The organisation's own access to its mailboxes (REQ-1923): a service account its Workspace
domain has delegated to, reading as each user in turn, and the mailboxes a source is to read --
every user of the domain, the members of a group, or a list -- as Google's Directory API lists
them.

Delegation is domain-wide: Google has no way to delegate a scope for some users and not
others, so which mailboxes are read is only what a source is told to read.

A refusal here is the setup's, not one mailbox's: the domain has not delegated a scope the
service account asks for, the administrator address is not one, or the directory will not be
read. It fails a build by name. The one refusal that is a mailbox's is :class:`NotAUser`: Google
says the address the service account was to read as is no user of the domain.

The key is held as given, by :class:`ServiceAccount` alone, and is never said: not in a
message, a log or a representation.
"""

# Requirements: REQ-1923
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from provisa.api_source.oauth_grants import CredentialRefused, access_token
from provisa.core.auth_models import ApiAuthGoogleServiceAccount
from provisa.google_workspace.settings import EVERYONE, GROUP, Mailboxes

_SCOPE = "https://www.googleapis.com/auth/"
#: Listing the domain's users (Directory API users.list).
USERS_SCOPE = f"{_SCOPE}admin.directory.user.readonly"
#: Listing a group's members (Directory API members.list).
MEMBERS_SCOPE = f"{_SCOPE}admin.directory.group.member.readonly"
BASE_URL = "https://admin.googleapis.com/admin/directory/v1/"
#: The most Google answers in one page of each list.
USERS_PAGE, MEMBERS_PAGE = 500, 200
_TIMEOUT = 30.0
#: Where a super administrator authorises the service account's client ID for scopes.
CONSOLE = (
    "the Google Admin console, Security > Access and data control > API controls > "
    "Manage Domain Wide Delegation"
)
# Google's token endpoint, for an address that is no user of the domain (its descriptions of
# invalid_grant for a service account acting as a user).
_NOT_A_USER = ("not a valid email", "invalid email or user id")


class DelegationRefused(RuntimeError):
    """The domain has not delegated, to the service account, a scope it asked for."""

    def __init__(self, scopes: tuple[str, ...], reason: str) -> None:
        self.scopes, self.reason = scopes, reason
        super().__init__(
            "the organisation's Google service account is not authorised for "
            f"{', '.join(scopes)} ({reason}): a super administrator adds the service "
            f"account's client ID with that scope in {CONSOLE}; a new authorisation can take "
            "up to 24 hours to apply"
        )


class NotAUser(RuntimeError):
    """Google says the address the service account was to read as is no user of the domain."""

    def __init__(self, address: str, reason: str) -> None:
        self.address, self.reason = address, reason
        super().__init__(f"{address} is not a user of the organisation's domain ({reason})")


class DirectoryRefused(RuntimeError):
    """The mailboxes a source is to read cannot be listed; the message says why."""

    def __init__(self, what: str, status: int, reason: str) -> None:
        self.status, self.reason = status, reason
        super().__init__(f"Google's directory refused {what}: {reason} (HTTP {status})")


#: Asks for an access token under a service-account credential (``oauth_grants.access_token``).
Grant = Callable[[ApiAuthGoogleServiceAccount], str]


class ServiceAccount:
    """The organisation's service account: a token to read as one user, for some scopes. The
    key is held as given and never said. Safe to call from any thread; a token is kept by the
    grant until shortly before it lapses."""

    def __init__(self, key: str, *, grant: Grant = access_token) -> None:
        self._key = key
        self._grant = grant

    def __repr__(self) -> str:
        return "ServiceAccount()"

    def token(self, subject: str, scopes: tuple[str, ...]) -> str:
        """An access token to act as ``subject`` under ``scopes``. Google's refusal is said by
        what it means: a scope not delegated (:class:`DelegationRefused`), an address that is
        no user (:class:`NotAUser`); any other stays the credential's own refusal."""
        try:
            return self._grant(
                ApiAuthGoogleServiceAccount(key=self._key, subject=subject, scopes=list(scopes))
            )
        except CredentialRefused as refused:
            reason = refused.reason
            if reason.startswith("unauthorized_client"):
                raise DelegationRefused(scopes, reason) from None
            if reason.startswith("invalid_grant") and any(
                said in reason.lower() for said in _NOT_A_USER
            ):
                raise NotAUser(subject, reason) from None
            raise


def _reason(answer: httpx.Response) -> str:
    try:
        error = answer.json().get("error") or {}
    except ValueError:
        return f"HTTP {answer.status_code}"
    if not isinstance(error, dict):
        return str(error)
    reasons = [e.get("reason") for e in error.get("errors") or [] if isinstance(e, dict)]
    said = error.get("message")
    named = next((r for r in reasons if r), None)
    return f"{named}: {said}" if named and said else str(said or named or answer.status_code)


class Directory:
    """The domain's directory, read as its administrator. ``token`` answers the access token
    for the scope a listing needs (called off the event loop)."""

    def __init__(self, token: Callable[[str], str], client: httpx.Client) -> None:
        self._token, self._client = token, client

    def _pages(self, what: str, path: str, params: dict[str, Any], scope: str, of: str):
        params = dict(params)
        while True:
            answer = self._client.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token(scope)}"},
                timeout=_TIMEOUT,
            )
            if answer.status_code != 200:
                raise DirectoryRefused(what, answer.status_code, _reason(answer))
            page = answer.json()
            yield page.get(of, [])
            token = page.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    def users(self) -> list[str]:
        """The address of every user of the domain that has a mailbox to read: not suspended,
        not a guest (a guest's address is outside the domain), and with its Google mailbox set
        up. They are left out here, not found out by a refusal."""
        found = []
        for page in self._pages(
            "the list of the domain's users",
            "users",
            {
                "customer": "my_customer",
                "maxResults": USERS_PAGE,
                "query": "isSuspended=false",
                "projection": "basic",
                "fields": "nextPageToken,users(primaryEmail,suspended,isGuestUser,isMailboxSetup)",
            },
            USERS_SCOPE,
            "users",
        ):
            for user in page:
                if user.get("suspended") or user.get("isGuestUser"):
                    continue
                if user.get("isMailboxSetup") is False:
                    continue
                address = user.get("primaryEmail")
                if isinstance(address, str) and address:
                    found.append(address.lower())
        return found

    def members(self, group: str) -> list[str]:
        """The addresses of a group's members that are users of the domain, those of the groups
        inside it included. A suspended member is left out; so is one outside the domain."""
        found = []
        for page in self._pages(
            f"the members of the group {group!r}",
            f"groups/{quote(group, safe='')}/members",
            {
                "includeDerivedMembership": "true",
                "maxResults": MEMBERS_PAGE,
                "fields": "nextPageToken,members(email,type,status)",
            },
            MEMBERS_SCOPE,
            "members",
        ):
            for member in page:
                if member.get("type") != "USER" or member.get("status") == "SUSPENDED":
                    continue
                address = member.get("email")
                if isinstance(address, str) and address:
                    found.append(address.lower())
        return found


def needed(choice: Mailboxes) -> tuple[str, ...]:
    """The scopes listing ``choice`` needs delegated; a list needs none (nothing is listed)."""
    if choice.kind == EVERYONE:
        return (USERS_SCOPE,)
    if choice.kind == GROUP:
        return (MEMBERS_SCOPE,)
    return ()


def mailboxes(directory: Directory, choice: Mailboxes) -> list[str]:
    """The addresses of the mailboxes ``choice`` names, in address order, each once."""
    if choice.kind == EVERYONE:
        found = directory.users()
    elif choice.kind == GROUP:
        assert choice.group is not None  # a group choice names its group (settings.parse)
        found = directory.members(choice.group)
    else:
        found = list(choice.addresses)
    return sorted(set(found))
