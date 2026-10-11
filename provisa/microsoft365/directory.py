# Copyright (c) 2026 Kenneth Stott
# Canary: edfbe31d-6847-4b62-9d88-890ec9ea92c6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The organisation's own access to its mailboxes (REQ-1923): the token of its Microsoft client
(the client-credentials grant, no person signing in) and the mailboxes a source is to read --
everyone in the directory, the members of a group, or a list -- as Microsoft Graph lists them.

A refusal here is the setup's, not one mailbox's: the client was not granted what it asks for,
or the directory cannot be read. It fails a build by name.
"""

# Requirements: REQ-1923
from __future__ import annotations

import base64
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from provisa.api_source.oauth_grants import CredentialRefused
from provisa.microsoft365.graph import Graph
from provisa.microsoft365.settings import EVERYONE, GROUP, ORGANISATION_SCOPE, Mailboxes

_TIMEOUT = 10.0
_REFUSED = (400, 401, 403)
_EXPIRY_MARGIN = 60.0
_USER_FIELDS = "mail,userPrincipalName,accountEnabled"
_PAGE = "999"
_GUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
CLIENT = "the organisation's Microsoft 365 client"


class DirectoryRefused(RuntimeError):
    """The mailboxes a source is to read cannot be listed; the message says why."""


#: The application permission each read needs, by the least privileged name Microsoft gives
#: it, and the permissions that grant as much (Graph's permission tables for list users, list
#: a group's transitive members, list messages).
USERS = "User.Read.All"
GROUP_MEMBERS = "GroupMember.Read.All"
MAIL_READ = "Mail.Read"
_GRANTS: dict[str, frozenset[str]] = {
    USERS: frozenset(
        {"User.Read.All", "User.ReadWrite.All", "Directory.Read.All", "Directory.ReadWrite.All"}
    ),
    GROUP_MEMBERS: frozenset(
        {
            "GroupMember.Read.All",
            "GroupMember.ReadWrite.All",
            "Group.Read.All",
            "Group.ReadWrite.All",
            "Directory.Read.All",
            "Directory.ReadWrite.All",
        }
    ),
    MAIL_READ: frozenset({"Mail.Read", "Mail.ReadWrite"}),
}


def carried(token: str) -> frozenset[str] | None:
    """The application permissions an access token of the client carries: its ``roles`` claim,
    which Microsoft fills with what an administrator consented to. A token with none has no
    such claim. None when the token cannot be read as one.

    This is a diagnosis of a refusal Microsoft already gave, so the signature is not checked;
    nothing is decided by it. The token itself is never said."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    roles = payload.get("roles", [])
    if not isinstance(roles, list):
        return None
    return frozenset(r for r in roles if isinstance(r, str))


@dataclass(frozen=True)
class Granted:
    """What the client's token carries, set against what a read needs."""

    carries: tuple[str, ...]  # every application permission in the token, in name order
    missing: tuple[str, ...]  # the needed ones nothing in the token grants


def lacks(roles: frozenset[str], need: str) -> bool:
    """Whether nothing in ``roles`` grants ``need``."""
    return not roles & _GRANTS[need]


def needed(choice: Mailboxes) -> tuple[str, ...]:
    """The permissions listing ``choice`` needs: a group's members are users, read as such."""
    if choice.kind == EVERYONE:
        return (USERS,)
    if choice.kind == GROUP:
        return (GROUP_MEMBERS, USERS)
    return ()


def granted(token: str, needs: tuple[str, ...]) -> Granted | None:
    """The token's permissions against ``needs``; None when the token cannot be read."""
    roles = carried(token)
    if roles is None:
        return None
    return Granted(tuple(sorted(roles)), tuple(need for need in needs if lacks(roles, need)))


#: Posts a token request: (address, form) -> (status, the answer's JSON).
Post = Callable[[str, dict[str, str]], tuple[int, dict]]


def _post(url: str, form: dict[str, str]) -> tuple[int, dict]:
    reply = httpx.post(url, data=form, timeout=_TIMEOUT)
    if reply.status_code not in (200, *_REFUSED):
        reply.raise_for_status()
    return reply.status_code, reply.json()


class ClientToken:
    """The organisation's client's access token, asked for again as it nears its end. Safe to
    call from the threads that read Graph. The secret is held as given and never said."""

    def __init__(
        self, token_url: str, client_id: str, client_secret: str, *, post: Post = _post
    ) -> None:
        self._url = token_url
        self._form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": ORGANISATION_SCOPE,
        }
        self._post = post
        self._guard = threading.Lock()
        self._token: str | None = None
        self._until = 0.0

    def __repr__(self) -> str:
        return "ClientToken()"

    def __call__(self) -> str:
        with self._guard:
            if self._token is not None and time.monotonic() < self._until - _EXPIRY_MARGIN:
                return self._token
            status, answer = self._post(self._url, self._form)
            if status in _REFUSED:
                reason = answer.get("error", "refused")
                described = answer.get("error_description")
                raise CredentialRefused(
                    CLIENT, f"{reason}: {described}" if described else str(reason)
                )
            # Microsoft states the token's life; a token whose life is not stated is not one
            # this reader can pace its renewal by.
            token = str(answer["access_token"])
            self._token = token
            self._until = time.monotonic() + float(answer["expires_in"])
            return token


def _address(user: dict) -> str | None:
    address = user.get("mail") or user.get("userPrincipalName")
    return address.lower() if isinstance(address, str) and address else None


#: What Graph requires of a query that narrows a group's members to one kind (an OData cast):
#: this header and ``$count`` (group: list transitive members, "ConsistencyLevel ... This header
#: and $count are required when using ... OData cast").
_ADVANCED = {"ConsistencyLevel": "eventual"}


#: Everyone in the directory is its members: a guest has no mailbox in the tenant. Graph
#: answers ``userType eq`` without the advanced-query header (its table of filters by property).
_MEMBERS = "userType eq 'Member'"


def _users(
    graph: Graph, path: str, *, advanced: bool = False, only: str | None = None
) -> list[str]:
    query = {"$select": _USER_FIELDS, "$top": _PAGE}
    if only is not None:
        query["$filter"] = only
    if advanced:
        query["$count"] = "true"
    addresses = []
    for page in graph.pages(path, query, headers=_ADVANCED if advanced else None):
        for user in page:
            # A disabled account is not read: it is left out here, not found out by a refusal.
            if user.get("accountEnabled") is False:
                continue
            address = _address(user)
            if address is not None:
                addresses.append(address)
    return addresses


def _group_id(graph: Graph, group: str) -> str:
    if _GUID.fullmatch(group):
        return group
    found = graph.get("/groups", {"$filter": f"mail eq '{group}'", "$select": "id"})["value"]
    if len(found) != 1:
        raise DirectoryRefused(
            f"the group {group!r} names {len(found)} groups in the directory; it must name one"
        )
    return found[0]["id"]


def mailboxes(graph: Graph, choice: Mailboxes) -> list[str]:
    """The addresses of the mailboxes ``choice`` names, in address order, each once. Everyone
    is every member of the directory; a guest named in a list, or reached through a group, is
    read like any other and reported if it cannot be."""
    if choice.kind == EVERYONE:
        found = _users(graph, "/users", only=_MEMBERS)
    elif choice.kind == GROUP:
        assert choice.group is not None  # a group choice names its group (settings.parse)
        group = _group_id(graph, choice.group)
        found = _users(
            graph, f"/groups/{group}/transitiveMembers/microsoft.graph.user", advanced=True
        )
    else:
        found = list(choice.addresses)
    return sorted(set(found))
