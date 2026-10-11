# Copyright (c) 2026 Kenneth Stott
# Canary: 744772fc-e9a1-4668-9390-f4bcdce4f886
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A role's data surface: one object, built whole and installed by one assignment.

A role is served through five things built from the same inputs — its GraphQL schema, the
compilation context its queries are lowered with, its row filters, its REST path map and its
proto. They were five maps, written one after another, and a request (on its own thread) read
them one after another: in between, a query was validated against the NEW schema and compiled
against the OLD context, and a just-registered table was an unhandled "Unknown root query
field" (#213).

``RoleSurface`` holds the five. A build makes one, complete, and installs it with a single
assignment into the runtime's ``surfaces``; a request takes it once (:func:`role_surface`) and
reads every part from that one object, so no request sees parts of two builds.

``state.schemas`` / ``contexts`` / ``rls_contexts`` / ``table_path_maps`` / ``proto_files`` remain
as views of ``surfaces`` — one part across all roles — for code that needs only that part. A
view holds nothing of its own. Product code never writes through one: the build is the one
writer (tests/unit/test_role_surface.py holds both rules).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class RoleSurface:
    """Everything one role is served through, from one build."""

    schema: Any = None  # graphql.GraphQLSchema
    context: Any = None  # compiler.sql_gen.CompilationContext
    rls: Any = None  # compiler.rls.RLSContext
    table_path_map: Any = None  # {gql field name -> {schema_name, table_name, domain_id}}
    proto: Any = None  # the role's .proto text


def role_surface(state: Any, role_id: str) -> RoleSurface | None:
    """The surface ``role_id`` is served through now, or None when it has none (a role with no
    data plane, or one this runtime does not know). Taken ONCE per request: every part a request
    reads comes from the object this returns."""
    return state.surfaces.get(role_id)


class SurfacePart(dict):
    """One part of every role's surface, as role id -> part: what ``surfaces`` held when this
    was taken.

    A plain dict to read — a role whose surface has no such part is not in it. It holds nothing
    the surfaces do not: it is made from them on every access to ``state.contexts`` and its
    siblings. A write goes through to ``surfaces``, replacing that role's surface with one that
    differs in that part alone (a single assignment), for a test that sets a state up part by
    part; the build installs whole surfaces and never comes here. Because it is a copy, one
    taken before a change is what a test's teardown puts back.
    """

    __slots__ = ("_surfaces", "_part")

    def __init__(self, surfaces: dict[str, RoleSurface], part: str) -> None:
        super().__init__(
            (role_id, getattr(held, part))
            for role_id, held in list(surfaces.items())
            if getattr(held, part) is not None
        )
        self._surfaces = surfaces
        self._part = part

    def __setitem__(self, role_id: str, value: Any) -> None:
        held = self._surfaces.get(role_id) or RoleSurface()
        self._surfaces[role_id] = replace(held, **{self._part: value})
        super().__setitem__(role_id, value)

    def __delitem__(self, role_id: str) -> None:
        super().__delitem__(role_id)  # KeyError when the role has no such part
        remaining = replace(self._surfaces[role_id], **{self._part: None})
        if remaining == RoleSurface():
            del self._surfaces[role_id]
        else:
            self._surfaces[role_id] = remaining

    _MISSING = object()

    def pop(self, role_id: str, default: Any = _MISSING) -> Any:
        if role_id not in self:
            if default is SurfacePart._MISSING:
                raise KeyError(role_id)
            return default
        value = self[role_id]
        del self[role_id]
        return value

    def clear(self) -> None:
        for role_id in list(self):
            del self[role_id]

    def update(self, *others: Any, **named: Any) -> None:
        for role_id, value in dict(*others, **named).items():
            self[role_id] = value

    def setdefault(self, role_id: str, default: Any = None) -> Any:
        if role_id not in self:
            self[role_id] = default
        return self[role_id]


def set_part(surfaces: dict[str, RoleSurface], part: str, values: dict[str, Any]) -> None:
    """Make ``part`` across all roles exactly ``values`` (a test replacing a whole map)."""
    view = SurfacePart(surfaces, part)
    for role_id in list(view):
        if role_id not in values:
            del view[role_id]
    for role_id, value in values.items():
        view[role_id] = value
