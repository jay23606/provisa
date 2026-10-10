# Copyright (c) 2026 Kenneth Stott
# Canary: f6d2c7de-7fe7-44ee-9839-bf9a487092ba
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Each organisation is served its own gRPC service, as its model stands now (REQ-045, REQ-1266).

One server, any number of organisations. A call is decoded, answered and described from the
service of the organisation it is bound to: its own methods, its own messages, its own
reflection. A change to an organisation's model is served by the next call."""

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

    def __init__(self, protos: dict[str, str]) -> None:
        self.protos = protos
        self._compiled: dict[str, OrgDescriptor] = {}

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
    state = _Deployment({"acme": _proto("Orders", "id"), "globex": _proto("Refunds", "ref")})

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


def _as(org: str) -> tuple:
    return (("x-provisa-org", org), ("x-provisa-role", "analyst"))


def _described(channel, org: str) -> descriptor_pb2.FileDescriptorProto:
    """The Provisa service as reflection describes it to a caller of ``org``."""
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    request = reflection_pb2.ServerReflectionRequest(
        file_containing_symbol="provisa.v1.ProvisaService"
    )
    (response,) = stub.ServerReflectionInfo(iter([request]), metadata=_as(org))
    (file,) = response.file_descriptor_response.file_descriptor_proto
    return descriptor_pb2.FileDescriptorProto.FromString(file)


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


def test_reflection_describes_each_organisation_its_own_service(deployment):
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
    # Its schema build writes the new service: a table added.
    state.protos["acme"] = _proto("Orders", "id").replace(
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
