# Copyright (c) 2026 Kenneth Stott
# Canary: d280573a-ab50-488c-bdc7-9b063e144637
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A ServiceNow instance's own REST APIs, read from what the instance publishes (REQ-1954).

- ``GET /api/now/doc``: the instance's list of its APIs, by namespace: each one's name, route and
  versions, with the HTTP method and route of each of its resources.
- ``GET /api/now/doc/oas_3?namespace=&name=&format=json&version=``: one API's OpenAPI 3
  document, the one the instance's REST API Explorer exports. It declares operations and their
  parameters; its request bodies have no schema (see ``openapi/mapper``: such a body is one
  untyped ``body``).

Both are read with the source's own credential, resolved at use. Nothing here is hand-written:
the APIs offered and their operations are the instance's.
"""

# Requirements: REQ-1954

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from provisa.core.secrets import resolve_secrets

#: How long one read of the instance's API list or of one API's document may take.
_TIMEOUT = 60.0


@dataclass(frozen=True)
class InstanceApi:
    """One API the instance publishes."""

    namespace: str
    name: str  # its display name, which the document export is asked for by
    route: str  # "now/import"
    description: str
    versions: tuple[str, ...]
    scripted: bool  # written on the instance (a Scripted REST API), not one of the platform's


class InstanceApiError(Exception):
    """The instance did not answer a read of its APIs: names the call and what it answered."""


def _client(instance_url: str, username: str, password: str) -> httpx.Client:
    return httpx.Client(
        base_url=resolve_secrets(instance_url).rstrip("/"),
        auth=(resolve_secrets(username), resolve_secrets(password)),
        headers={"Accept": "application/json"},
        timeout=_TIMEOUT,
    )


def _get(client: httpx.Client, path: str, params: dict[str, str] | None = None) -> Any:
    resp = client.get(path, params=params)
    if resp.is_error:
        raise InstanceApiError(f"{path}: HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def instance_apis(catalog: dict) -> list[InstanceApi]:
    """The APIs of an ``/api/now/doc`` answer, by namespace and name."""
    apis = []
    for namespace, by_name in sorted(catalog["result"].items()):
        for name, api in sorted(by_name.items()):
            apis.append(
                InstanceApi(
                    namespace=namespace,
                    name=name,
                    route=api["route"],
                    description=api.get("description") or "",
                    versions=tuple(api.get("versions") or ()),
                    scripted=bool(api.get("scripted")),
                )
            )
    return apis


def list_instance_apis(instance_url: str, username: str, password: str) -> list[InstanceApi]:
    """Every API the instance publishes (``/api/now/doc``)."""
    with _client(instance_url, username, password) as client:
        return instance_apis(_get(client, "/api/now/doc"))


def fetch_api_spec(
    instance_url: str,
    username: str,
    password: str,
    namespace: str,
    name: str,
    version: str = "latest",
) -> dict:
    """The OpenAPI 3 document the instance exports for one of its APIs."""
    with _client(instance_url, username, password) as client:
        spec = _get(
            client,
            "/api/now/doc/oas_3",
            {"namespace": namespace, "name": name, "format": "json", "version": version},
        )
    if "error" in spec or "paths" not in spec:
        raise InstanceApiError(f"{namespace}/{name}: the instance exported no document: {spec}")
    return spec


def merged_spec(title: str, instance_url: str, specs: list[dict]) -> dict:
    """One OpenAPI document holding the operations of every one of ``specs``, addressed at the
    instance: the document an OpenAPI source reads its tables and commands from. Two of them
    declaring the same operation is refused by name: a path is one API's."""
    paths: dict[str, Any] = {}
    for spec in specs:
        for path, item in spec["paths"].items():
            if path in paths:
                raise InstanceApiError(f"{path} is declared by two of the instance's APIs")
            paths[path] = item
    return {
        "openapi": "3.0.1",
        "info": {"title": title, "version": "latest"},
        "servers": [{"url": resolve_secrets(instance_url).rstrip("/")}],
        "paths": paths,
    }
