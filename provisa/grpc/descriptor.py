# Copyright (c) 2026 Kenneth Stott
# Canary: e68ffb04-4236-48f5-8b90-262250aef2d0
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An organisation's gRPC service, compiled: its messages, its methods, its reflection.

An organisation's schema build writes two kinds of proto text. One for the WIRE
(``OrgRuntime.wire_proto``): the union of every role's surface, which requests are decoded and
answers encoded with. And one per ROLE (``proto_files``, a part of each role's surface, meta-roles
included): what that role is served, as its GraphQL schema is — the file a client of that role
downloads. Field numbers are shared, so a role's proto is a subset of the wire's that reads the
same bytes.

Each is compiled here into a descriptor pool of its own — every file is ``provisa.v1``, so no
two fit in one pool — and kept on the organisation's runtime for as long as the text it was
compiled from is the text the runtime holds. A call is decoded and answered with its
organisation's wire descriptor; what a caller is DESCRIBED (server reflection) is its role's.
A model change is served as soon as its build has written the new text."""

# Requirements: REQ-045, REQ-051, REQ-1266

from __future__ import annotations

from typing import Any

SERVICE_NAME = "provisa.v1.ProvisaService"
_PACKAGE = "provisa.v1"


class OrgDescriptor:
    """One compiled service. Its message classes are its attributes, by message name — the
    names a generated module gives them."""

    def __init__(self, proto: str) -> None:
        from google.protobuf import descriptor_pb2, descriptor_pool

        from provisa.grpc.schema_gen import compile_descriptor_set

        self.proto = proto
        self.pool = descriptor_pool.DescriptorPool()
        files = descriptor_pb2.FileDescriptorSet.FromString(compile_descriptor_set(proto))
        for file in files.file:  # protoc writes a set in dependency order
            self.pool.Add(file)
        self._classes: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        found = self._classes.get(name)
        if found is None:
            from google.protobuf import message_factory

            try:
                message = self.pool.FindMessageTypeByName(f"{_PACKAGE}.{name}")
            except KeyError:
                raise AttributeError(f"the service has no message {name!r}") from None
            found = self._classes[name] = message_factory.GetMessageClass(message)
        return found

    def method(self, name: str) -> Any | None:
        """The service's method ``name`` (its descriptor), or None when the service has none."""
        return self.pool.FindServiceByName(SERVICE_NAME).methods_by_name.get(name)

    def request_class(self, method: Any) -> Any:
        return self._class_of(method.input_type)

    def _class_of(self, message: Any) -> Any:
        from google.protobuf import message_factory

        return message_factory.GetMessageClass(message)


def bound_descriptor(state: Any) -> OrgDescriptor | None:
    """The compiled service of the organisation ``state`` is bound to, or None when its build
    has written none. Compiled when first asked for, and again whenever the organisation's
    proto text is no longer the text it was compiled from."""
    proto = state.wire_proto  # the bound organisation's (AppState.wire_proto)
    if not proto:
        return None
    held = state.grpc_descriptor
    if held is None or held.proto != proto:
        held = state.grpc_descriptor = OrgDescriptor(proto)
    return held


def role_descriptor(state: Any, role_id: str) -> OrgDescriptor | None:
    """The compiled service ``role_id`` is served in the organisation ``state`` is bound to —
    from the role's own proto, the text its clients download (``proto_files``) — or None for a
    role with none (no data surface, or not a role of this organisation). Compiled when first
    asked for and again when the role's proto has changed: a rebuilt role, a meta-role whose
    members changed."""
    proto = state.proto_files.get(role_id)
    if not proto:
        return None
    kept = state.grpc_role_descriptors
    held = kept.get(role_id)
    if held is None or held.proto != proto:
        held = kept[role_id] = OrgDescriptor(proto)
    return held
