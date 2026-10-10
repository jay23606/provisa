# Copyright (c) 2026 Kenneth Stott
# Canary: f6d2c7de-7fe7-44ee-9839-bf9a487092ba
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a caller discovers over gRPC is what its role is served, as its model stands now
(REQ-045, REQ-051, REQ-1266).

One server, any number of organisations and roles. Server reflection describes a caller the
service of the role it runs as, in its organisation -- the proto that role downloads, the tables
and columns its GraphQL schema has. A call is decoded and answered with its organisation's own
messages. A change to a role or to a model is described and served by the next call."""

# Requirements: REQ-045, REQ-051, REQ-1266

from __future__ import annotations

import socket

import grpc
import pytest
from google.protobuf import descriptor_pb2
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from provisa.core.request_context import current_org
from provisa.grpc import server as grpc_server
from provisa.grpc.descriptor import OrgDescriptor, bound_descriptor

pytestmark = pytest.mark.unit


def _proto(table: str, column: str) -> str:
    return f"""syntax = "proto3";
package provisa.v1;
message {table} {{ int32 {column} = 1; }}
message {table}Request {{ int32 limit = 1; }}
service ProvisaService {{ rpc Query{table} ({table}Request) returns (stream {table}); }}
"""


class _Deployment:
    """A server process's state: each organisation's service is its own, read as the bound
    organisation's (what AppState.wire_proto and .grpc_descriptor are)."""

    multitenancy = True
    security_high = False

    def __init__(self, protos: dict[str, str], roles: dict[str, dict[str, str]] | None = None):
        self.protos = protos  # organisation -> the proto its wire is encoded with
        self.roles = roles or {}  # organisation -> role -> the proto that role is served
        self._compiled: dict[str, OrgDescriptor] = {}
        self._role_compiled: dict[str, dict] = {}

    @property
    def proto_files(self) -> dict[str, str]:
        return self.roles.get(current_org.get(), {})

    @property
    def grpc_role_descriptors(self) -> dict:
        return self._role_compiled.setdefault(current_org.get(), {})

    @property
    def wire_proto(self) -> str | None:
        return self.protos.get(current_org.get())

    @property
    def grpc_descriptor(self):
        return self._compiled.get(current_org.get())

    @grpc_descriptor.setter
    def grpc_descriptor(self, value) -> None:
        self._compiled[current_org.get()] = value


@pytest.fixture
def deployment(monkeypatch):
    """A real server on a loopback port over two organisations with different models. Each
    table's query handler is stood in for: it answers one row carrying the request's limit, in
    the bound organisation's own message."""
    state = _Deployment(
        {"acme": _proto("Orders", "id"), "globex": _proto("Refunds", "ref")},
        {
            "acme": {"analyst": _proto("Orders", "id")},
            "globex": {"analyst": _proto("Refunds", "ref")},
        },
    )

    async def _built(_org_id):
        return None

    async def _rows(self, request, context, type_name, role_id):
        message = getattr(self._pb2, type_name)
        (field,) = message.DESCRIPTOR.fields
        yield message(**{field.name: request.limit})

    monkeypatch.setattr("provisa.api.app.ensure_serving_runtime", _built)
    monkeypatch.setattr("provisa.grpc.auth.auth_active", lambda _state: False)
    monkeypatch.setattr(grpc_server, "_allow_unsecured_reflection", lambda: True)
    monkeypatch.setattr(grpc_server.ProvisaServicer, "_handle_query_bound", _rows)
    monkeypatch.setattr(grpc_server.ProvisaServicer, "_meter_msg", lambda self, msg: msg)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = grpc_server.start_grpc_server(port, state)
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield state, channel
    finally:
        channel.close()
        server.stop(grace=0).wait()


def _as(org: str, role: str = "analyst") -> tuple:
    return (("x-provisa-org", org), ("x-provisa-role", role))


def _reflected(channel, metadata: tuple) -> descriptor_pb2.FileDescriptorProto:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    request = reflection_pb2.ServerReflectionRequest(
        file_containing_symbol="provisa.v1.ProvisaService"
    )
    (response,) = stub.ServerReflectionInfo(iter([request]), metadata=metadata)
    # The file, and after it the files it imports (the well-known types a service names).
    files = [
        descriptor_pb2.FileDescriptorProto.FromString(raw)
        for raw in response.file_descriptor_response.file_descriptor_proto
    ]
    (file,) = [f for f in files if f.package == "provisa.v1"]
    return file


def _described(channel, org: str, role: str = "analyst") -> descriptor_pb2.FileDescriptorProto:
    """The Provisa service as reflection describes it to a caller of ``org`` acting as ``role``."""
    return _reflected(channel, _as(org, role))


def _query(channel, org: str, table: str, limit: int) -> list[bytes]:
    call = channel.unary_stream(
        f"/provisa.v1.ProvisaService/Query{table}",
        request_serializer=lambda raw: raw,
        response_deserializer=lambda raw: raw,
    )
    request = bound_for(org, table)(limit=limit).SerializeToString()
    return list(call(request, metadata=_as(org)))


def bound_for(org: str, table: str):
    """The request class of ``table`` as ``org``'s own client would have generated it."""
    protos = {"acme": _proto("Orders", "id"), "globex": _proto("Refunds", "ref")}
    return getattr(OrgDescriptor(protos.get(org) or _proto(table, "id")), f"{table}Request")


def test_two_organisations_are_never_described_each_others_service(deployment):
    _state, channel = deployment
    acme, globex = _described(channel, "acme"), _described(channel, "globex")
    assert [m.name for m in acme.message_type] == ["Orders", "OrdersRequest"]
    assert [m.name for m in globex.message_type] == ["Refunds", "RefundsRequest"]
    assert [m.name for m in acme.service[0].method] == ["QueryOrders"]
    assert [m.name for m in globex.service[0].method] == ["QueryRefunds"]


def test_a_call_is_decoded_and_answered_with_its_organisations_own_messages(deployment):
    state, channel = deployment
    (row,) = _query(channel, "acme", "Orders", 7)
    assert OrgDescriptor(state.protos["acme"]).Orders.FromString(row).id == 7
    (row,) = _query(channel, "globex", "Refunds", 9)
    assert OrgDescriptor(state.protos["globex"]).Refunds.FromString(row).ref == 9


def test_a_method_of_another_organisations_service_is_not_this_callers(deployment):
    _state, channel = deployment
    call = channel.unary_stream(
        "/provisa.v1.ProvisaService/QueryRefunds",
        request_serializer=lambda raw: raw,
        response_deserializer=lambda raw: raw,
    )
    with pytest.raises(grpc.RpcError) as refused:
        list(call(b"", metadata=_as("acme")))
    assert refused.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_a_call_that_names_no_organisation_is_described_and_served_nothing(deployment):
    _state, channel = deployment
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    request = reflection_pb2.ServerReflectionRequest(
        file_containing_symbol="provisa.v1.ProvisaService"
    )
    with pytest.raises(grpc.RpcError) as refused:
        list(stub.ServerReflectionInfo(iter([request])))
    assert refused.value.code() == grpc.StatusCode.UNAUTHENTICATED
    call = channel.unary_stream(
        "/provisa.v1.ProvisaService/QueryOrders",
        request_serializer=lambda raw: raw,
        response_deserializer=lambda raw: raw,
    )
    with pytest.raises(grpc.RpcError) as refused:
        list(call(b"", metadata=(("x-provisa-role", "analyst"),)))
    assert refused.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_a_change_to_an_organisations_model_is_served_by_the_next_call(deployment):
    state, channel = deployment
    assert [m.name for m in _described(channel, "acme").service[0].method] == ["QueryOrders"]
    # Its schema build writes the new service, for the wire and for the role: a table added.
    state.protos["acme"] = state.roles["acme"]["analyst"] = _proto("Orders", "id").replace(
        "service ProvisaService {",
        "message Returns { int32 id = 1; }\nmessage ReturnsRequest { int32 limit = 1; }\n"
        "service ProvisaService { rpc QueryReturns (ReturnsRequest) returns (stream Returns);",
    )
    described = _described(channel, "acme")
    assert sorted(m.name for m in described.service[0].method) == ["QueryOrders", "QueryReturns"]
    call = channel.unary_stream(
        "/provisa.v1.ProvisaService/QueryReturns",
        request_serializer=lambda raw: raw,
        response_deserializer=lambda raw: raw,
    )
    compiled = OrgDescriptor(state.protos["acme"])
    (row,) = call(compiled.ReturnsRequest(limit=4).SerializeToString(), metadata=_as("acme"))
    assert compiled.Returns.FromString(row).id == 4
    # The other organisation's service is as it was.
    assert [m.name for m in _described(channel, "globex").service[0].method] == ["QueryRefunds"]


def test_a_service_is_compiled_once_for_the_text_it_was_written_as():
    state = _Deployment({"acme": _proto("Orders", "id")})
    token = current_org.set("acme")
    try:
        first = bound_descriptor(state)
        assert bound_descriptor(state) is first
        state.protos["acme"] = _proto("Orders", "number")
        assert bound_descriptor(state) is not first
    finally:
        current_org.reset(token)
    other = current_org.set("nobody")
    try:
        assert bound_descriptor(state) is None
    finally:
        current_org.reset(other)


# --- what a role is described is what that role is served -----------------------------------------


def test_a_role_is_described_its_own_proto_not_the_organisations_union(deployment):
    """The wire carries every table of the organisation; a role is described its own."""
    state, channel = deployment
    union = _proto("Orders", "id").replace(
        "service ProvisaService {",
        "message Ledger { int32 id = 1; }\nmessage LedgerRequest { int32 limit = 1; }\n"
        "service ProvisaService { rpc QueryLedger (LedgerRequest) returns (stream Ledger);",
    )
    state.protos["acme"] = union
    state.roles["acme"] = {"analyst": _proto("Orders", "id"), "auditor": union}
    assert [m.name for m in _described(channel, "acme").message_type] == [
        "Orders",
        "OrdersRequest",
    ]
    assert sorted(m.name for m in _described(channel, "acme", "auditor").service[0].method) == [
        "QueryLedger",
        "QueryOrders",
    ]


def test_a_role_with_no_service_and_a_call_naming_no_role_are_described_nothing(deployment):
    _state, channel = deployment
    for metadata, status in (
        (_as("acme", "nobody"), grpc.StatusCode.NOT_FOUND),
        ((("x-provisa-org", "acme"),), grpc.StatusCode.UNAUTHENTICATED),
    ):
        with pytest.raises(grpc.RpcError) as refused:
            _reflected(channel, metadata)
        assert refused.value.code() == status


def test_a_change_to_a_role_is_described_by_the_next_call(deployment):
    """A meta-role is a role built from the roles its caller holds; when its members change its
    surface is rebuilt, its proto with it, and the next reflection call describes that."""
    state, channel = deployment
    state.roles["acme"]["meta:a+b"] = _proto("Orders", "id")
    assert [m.name for m in _described(channel, "acme", "meta:a+b").message_type] == [
        "Orders",
        "OrdersRequest",
    ]
    state.roles["acme"]["meta:a+b"] = _proto("Orders", "id").replace(
        "message Orders { int32 id = 1; }", "message Orders { int32 id = 1; string note = 2; }"
    )
    orders = _described(channel, "acme", "meta:a+b").message_type[0]
    assert [f.name for f in orders.field] == ["id", "note"]
    # Another role of the same organisation is described as before.
    assert [f.name for f in _described(channel, "acme").message_type[0].field] == ["id"]


@pytest.fixture
def built(monkeypatch):
    """A real server over the real state after the real role build: two roles of one
    organisation, each reaching one domain."""
    from tests.unit.test_empty_domain_access_reaches_nothing import _built_roles

    monkeypatch.setenv("PROVISA_SINGLE_DOMAIN", "false")
    state = _built_roles(
        monkeypatch,
        [
            {"id": "sales_reader", "capabilities": ["usage"], "domain_access": ["sales"]},
            {"id": "finance_reader", "capabilities": ["usage"], "domain_access": ["finance"]},
        ],
    )
    monkeypatch.setattr("provisa.grpc.auth.auth_active", lambda _state: False)
    monkeypatch.setattr(grpc_server, "_allow_unsecured_reflection", lambda: True)
    monkeypatch.setattr(state, "security_high", False, raising=False)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = grpc_server.start_grpc_server(port, state)
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield state, channel
    finally:
        channel.close()
        server.stop(grace=0).wait()


def _service(file: descriptor_pb2.FileDescriptorProto) -> tuple[set[str], dict[str, list[str]]]:
    methods = {m.name for s in file.service for m in s.method}
    return methods, {m.name: [f.name for f in m.field] for m in file.message_type}


@pytest.mark.parametrize(
    ("role", "has", "has_not"),
    [("sales_reader", "Orders", "Ledger"), ("finance_reader", "Ledger", "Orders")],
)
def test_reflection_lists_exactly_what_the_roles_own_proto_lists(built, role, has, has_not):
    """The role's proto is what its build made for it beside its GraphQL schema, and what it
    downloads (GET /data/proto/{role}). Reflection describes that file: every method and every
    message field of it, and no table of a domain the role does not reach."""
    from provisa.grpc.schema_gen import compile_descriptor_set

    state, channel = built
    described = _reflected(channel, (("x-provisa-role", role),))
    files = descriptor_pb2.FileDescriptorSet.FromString(
        compile_descriptor_set(state.proto_files[role])
    )
    (own,) = [f for f in files.file if f.package == "provisa.v1"]
    assert _service(described) == _service(own)
    methods, messages = _service(described)
    assert f"Query{has}" in methods and has in messages
    assert f"Query{has_not}" not in methods and has_not not in messages
    # The table its GraphQL schema offers is the one its service queries.
    (field,) = state.schemas[role].query_type.fields
    assert f"Query{field.capitalize()}" in methods
    # The wire, which no caller is described, carries both.
    assert {"QueryOrders", "QueryLedger"} <= _service(
        [
            f
            for f in descriptor_pb2.FileDescriptorSet.FromString(
                compile_descriptor_set(state.wire_proto)
            ).file
            if f.package == "provisa.v1"
        ][0]
    )[0]


def test_a_meta_role_is_described_what_its_members_are_served_together(built, monkeypatch):
    """A caller holding two roles acts as their meta-role, built on first use with a surface of
    its own -- GraphQL schema and proto alike. It is described that surface with no restart."""
    from provisa.security.meta_role import ensure_meta_role

    state, channel = built
    for name in ("meta_roles", "meta_resolved_at", "masking_rules"):
        monkeypatch.setattr(state._active_runtime(), name, {}, raising=False)
    meta = ensure_meta_role(state, ["sales_reader", "finance_reader"])
    methods, messages = _service(_reflected(channel, (("x-provisa-role", meta),)))
    assert {"QueryOrders", "QueryLedger"} <= methods
    assert sorted(state.schemas[meta].query_type.fields) == ["ledger", "orders"]
    # Each member alone is still described its own.
    alone, _ = _service(_reflected(channel, (("x-provisa-role", "sales_reader"),)))
    assert "QueryLedger" not in alone
