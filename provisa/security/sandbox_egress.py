# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Where a sandbox's sources may point (REQ-2006).

A sandbox's visitor may register a source -- that is the point of a sandbox -- and Provisa then
connects to wherever the source points, from inside the deployment. A destination on a private,
loopback, link-local or otherwise non-public address would therefore be reached from the
deployment's own network: its control-plane database, its cache, a cloud metadata endpoint. A
source of a sandbox org (a demo sandbox, a demo template, or the hosted sandbox org of REQ-1598)
may not resolve to any such address.

One check, :func:`require_public_destination`, is asked at each point a sandbox's source gains or
uses a destination: when it is registered or changed, and when Provisa connects to it -- again,
because the name may resolve differently by then -- including each redirect an HTTP source
follows. It resolves the name and refuses, by name, when ANY address it resolves to is not public.
"""

# Requirements: REQ-2006, REQ-1598

from __future__ import annotations

import ipaddress
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from provisa.core.org_ids import is_sandbox_tier_org

if TYPE_CHECKING:
    import httpx

#: The REQ-1598 hosted sandbox org.
_HOSTED_SANDBOX_ORG = "sandbox"


class PrivateDestinationRefused(PermissionError):
    """A sandbox's source names a destination that is not on the public internet."""

    code = "sources.private_destination"

    def __init__(self, host: str, address: str) -> None:
        super().__init__(
            f"A sandbox's sources may reach only public addresses; {host!r} is {address}, "
            "which is not one"
        )
        self.params = {"host": host, "address": address}


def confined(org_id: str | None) -> bool:
    """Whether ``org_id``'s sources are held to public destinations: a sandbox org."""
    return org_id is not None and (is_sandbox_tier_org(org_id) or org_id == _HOSTED_SANDBOX_ORG)


def _public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def resolve(host: str, port: int | None = None) -> list[str]:
    """Every address ``host`` resolves to now (an IP literal is itself)."""
    try:
        return [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        # A name with no address now cannot be shown to be public, and may be given one later.
        raise PrivateDestinationRefused(host, "a name that does not resolve") from exc
    return sorted({str(info[4][0]) for info in infos})


def require_public_destination(host: str | None, port: int | None = None) -> list[str]:
    """The addresses ``host`` resolves to, refused by name when any is not public. A source with
    no network host (an uploaded file, an embedded store) has nothing to check."""
    if not host:
        return []
    addresses = resolve(host, port)
    for address in addresses:
        if not _public(ipaddress.ip_address(address)):
            raise PrivateDestinationRefused(host, address)
    return addresses


# --- what a sandbox org may reach -------------------------------------------------------------
#
# A demo's own sources are the operator's: its template's configuration names them (the demo's
# shared, read-only database is on the deployment's private network by design). Each sandbox org's
# runtime records them when it is built (app._build_org_runtime), and a destination among them is
# reached whatever its address; every other destination must be public.

_demo_destinations: dict[str, frozenset[tuple[str, int | None]]] = {}

#: A network-host source with no host given is reached at this host (schema_common._add_source_pool).
_DEFAULT_HOST = "localhost"
_URL_FIELDS = ("path", "base_url")


def _plain(value: object) -> str | None:
    """``value`` with any secret reference resolved -- a source may name its host as
    ``${secret:NAME}``, and the address it reaches is the resolved one."""
    if not isinstance(value, str) or not value:
        return None
    from provisa.core.secrets import resolve_secrets

    return str(resolve_secrets(value))


def _url_destination(url: str | None) -> tuple[str, int | None] | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() not in _NETWORK_SCHEMES or not parts.hostname:
        return None
    return parts.hostname.lower(), parts.port


_NETWORK_SCHEMES = ("http", "https", "ftp", "sftp", "s3", "gs", "ws", "wss", "postgresql", "mysql")


def destinations(fields: dict) -> list[tuple[str, int | None]]:
    """Every network destination a source names, from its fields: ``host``/``port``, a URL in
    ``path`` or ``base_url``, and any URL among the values of ``federation_hints`` and ``mapping``
    (an object store's endpoint, a crawl's start). A network source given a port and no host is
    reached at localhost, so that is its destination."""
    found: list[tuple[str, int | None]] = []
    host = _plain(fields.get("host"))
    port = fields.get("port") or None
    if host:
        found.append((host.lower(), port))
    elif port:
        found.append((_DEFAULT_HOST, port))
    for name in _URL_FIELDS:
        url = _url_destination(_plain(fields.get(name)))
        if url is not None:
            found.append(url)
    for bag in ("federation_hints", "mapping"):
        for value in _strings(fields.get(bag)):
            url = _url_destination(_plain(value))
            if url is not None:
                found.append(url)
    return found


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, (list, tuple)):
        return [s for v in node for s in _strings(v)]
    return []


def set_demo_destinations(org_id: str, sources: list[dict]) -> None:
    """Record what the demo of sandbox org ``org_id`` declares, from its configuration's sources."""
    _demo_destinations[org_id] = frozenset(d for s in sources for d in destinations(s))


def forget(org_id: str) -> None:
    _demo_destinations.pop(org_id, None)


def _org(org_id: str | None) -> str | None:
    if org_id is not None:
        return org_id
    from provisa.core.request_context import current_org

    return current_org.get(None)


def require_allowed(host: str, port: int | None, org_id: str | None = None) -> None:
    """Refuse, by name, ``host`` for a sandbox org unless its demo declares it or every address
    it resolves to is public. Any other org reaches what it names."""
    org = _org(org_id)
    if not confined(org):
        return
    assert org is not None
    if (host.lower(), port) in _demo_destinations.get(org, frozenset()):
        return
    require_public_destination(host, port)


def require_source_allowed(fields: dict, org_id: str | None = None) -> None:
    """:func:`require_allowed` for every destination a source names (:func:`destinations`)."""
    org = _org(org_id)
    if not confined(org):
        return
    for host, port in destinations(fields):
        require_allowed(host, port, org)


def source_fields(source: object) -> dict:
    """The address-bearing fields of a registered :class:`provisa.core.models.Source`."""
    return {
        "host": source.host,  # type: ignore[attr-defined]
        "port": source.port,  # type: ignore[attr-defined]
        "path": source.path,  # type: ignore[attr-defined]
        "base_url": source.base_url,  # type: ignore[attr-defined]
        "federation_hints": source.federation_hints,  # type: ignore[attr-defined]
        "mapping": source.mapping,  # type: ignore[attr-defined]
    }


def http_event_hooks(org_id: str | None = None) -> dict:
    """httpx event hooks that check each request a sandbox org's source makes -- every redirect
    is a request of its own -- before it is sent. Empty for any other org."""
    org = _org(org_id)
    if not confined(org):
        return {}

    def _check(request: object) -> None:
        url = request.url  # type: ignore[attr-defined]
        require_allowed(url.host, url.port, org)

    async def _acheck(request: object) -> None:
        _check(request)

    return {"request": [_acheck]}


def http_sync_event_hooks(org_id: str | None = None) -> dict:
    """:func:`http_event_hooks` for a synchronous ``httpx.Client``."""
    org = _org(org_id)
    if not confined(org):
        return {}

    def _check(request: object) -> None:
        url = request.url  # type: ignore[attr-defined]
        require_allowed(url.host, url.port, org)

    return {"request": [_check]}


def checked_get(url: str, *, timeout: float) -> "httpx.Response":
    """``httpx.get(url, follow_redirects=True)``, with every hop of a sandbox org's request
    checked (:func:`http_sync_event_hooks`)."""
    import httpx

    with httpx.Client(
        timeout=timeout, follow_redirects=True, event_hooks=http_sync_event_hooks()
    ) as client:
        return client.get(url)


def require_allowed_address(server_address: str) -> None:
    """:func:`require_allowed` for a ``host:port`` address (a gRPC target)."""
    host, _, port = server_address.rpartition(":")
    if not host:
        host, port = server_address, ""
    require_allowed(host.strip("[]"), int(port) if port.isdigit() else None)


def require_allowed_url(url: str) -> None:
    """:func:`require_allowed` for the host of ``url``."""
    parts = urlsplit(url)
    if parts.hostname:
        require_allowed(parts.hostname, parts.port)


def require_registered_source_allowed(source: object, org_id: str | None = None) -> None:
    """:func:`require_source_allowed` for a registered source, read only for a sandbox org."""
    org = _org(org_id)
    if not confined(org):
        return
    require_source_allowed(source_fields(source), org)
