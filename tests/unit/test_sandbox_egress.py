# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-2006: a sandbox org's sources reach only the destinations its demo declares and public
addresses -- checked when a source is saved, at each connection, and at every redirect hop."""

# Requirements: REQ-2006, REQ-1598

from __future__ import annotations

import asyncio

import httpx
import pytest

from provisa.core.request_context import reset_current_org, set_current_org
from provisa.security import sandbox_egress as egress

_SANDBOX = "sbx0123456789ab"
_PRIVATE = [
    "10.1.2.3",
    "172.16.0.9",
    "172.31.255.1",
    "192.168.4.4",
    "127.0.0.1",
    "169.254.169.254",
    "100.64.0.1",
    "0.0.0.0",
    "::1",
    "fc00::1",
    "fd00::5",
    "fe80::1",
    "::ffff:10.0.0.1",
]


@pytest.fixture
def in_sandbox():
    egress.set_demo_destinations(_SANDBOX, [{"host": "weblogs-db", "port": 5432}])
    token = set_current_org(_SANDBOX)
    yield
    reset_current_org(token)
    egress.forget(_SANDBOX)


@pytest.mark.parametrize("org", [_SANDBOX, "sbxtplweblogs", "sandbox"])
def test_every_kind_of_sandbox_org_is_confined(org):
    assert egress.confined(org)


def test_an_ordinary_org_is_not_confined():
    assert not egress.confined("acme")
    egress.require_allowed("10.0.0.1", 5432, "acme")


@pytest.mark.parametrize("address", _PRIVATE)
def test_a_sandbox_source_on_a_private_address_is_refused(in_sandbox, address):
    with pytest.raises(egress.PrivateDestinationRefused) as refused:
        egress.require_source_allowed({"host": address, "port": 5432})
    assert refused.value.code == "sources.private_destination"


def test_a_name_resolving_to_a_private_address_is_refused(in_sandbox):
    with pytest.raises(egress.PrivateDestinationRefused):
        egress.require_allowed("localhost", 5432)


def test_a_source_with_a_port_and_no_host_is_localhost_and_refused(in_sandbox):
    with pytest.raises(egress.PrivateDestinationRefused):
        egress.require_source_allowed({"host": "", "port": 5432})


def test_urls_in_path_hints_and_mapping_are_checked(in_sandbox):
    for fields in (
        {"path": "http://169.254.169.254/latest/meta-data/"},
        {"base_url": "https://10.0.0.8/api"},
        {"federation_hints": {"endpoint": "http://192.168.1.1:9000"}},
        {"mapping": {"crawl": {"start": "http://127.0.0.1:8080/"}}},
    ):
        with pytest.raises(egress.PrivateDestinationRefused):
            egress.require_source_allowed(fields)


def test_the_demos_own_destination_and_a_public_one_are_reached(in_sandbox):
    egress.require_source_allowed({"host": "weblogs-db", "port": 5432})
    egress.require_source_allowed({"host": "8.8.8.8", "port": 443})
    egress.require_source_allowed({"path": "/data/orders.csv"})  # not a network destination
    with pytest.raises(egress.PrivateDestinationRefused):
        egress.require_allowed("weblogs-db", 5433)  # the demo's host, another port: not declared


def test_a_redirect_to_a_private_address_is_refused_before_it_is_sent(in_sandbox):
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
            event_hooks=egress.http_event_hooks(),
        ) as client:
            await client.get("http://8.8.8.8/start")

    with pytest.raises(egress.PrivateDestinationRefused):
        asyncio.run(fetch())
    assert sent == ["http://8.8.8.8/start"]


def test_a_grpc_target_is_checked(in_sandbox):
    with pytest.raises(egress.PrivateDestinationRefused):
        egress.require_allowed_address("10.0.0.2:50051")
    egress.require_allowed_address("8.8.8.8:443")


def test_the_direct_pool_refuses_before_it_connects(in_sandbox):
    from provisa.executor.pool import SourcePool

    with pytest.raises(egress.PrivateDestinationRefused):
        asyncio.run(SourcePool().add("probe", "postgresql", "127.0.0.1", 5432, "x", "u", "p"))
