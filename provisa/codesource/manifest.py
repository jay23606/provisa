# Copyright (c) 2026 Kenneth Stott
# Canary: c3d79418-e2eb-4760-8dd3-6cdcab732867
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a code source's bundle offers, from what its declarations say (REQ-1984, REQ-1993).

Every language's reader writes the same document (docs/arch/code-sources.md, section 2); Node's
(provisa/node/reader.mjs) writes every export of the bundle's entry module with its
JSDoc tags and its signature's types as trees. This module applies REQ-1984's rules to that:

- an export tagged ``@table`` is a table, ``@command`` a command, ``@stream`` a live table;
  untagged exports are ignored;
- a tag that is neither one of those nor a standard JSDoc tag is a problem named by the export
  and the tag;
- a ``@table`` returns a collection (an array or an iterable, synchronous or asynchronous) whose
  elements are its rows; one that returns a single object is a problem by name;
- a ``@stream`` is an async generator (its declaration returns ``AsyncGenerator<T>`` or
  ``AsyncIterable<T>``), with the same parameter and column rules as ``@table``;
- a non-optional parameter is required by the source; an optional one is not;
- the columns are the row type's fields, or -- when the row type is loose (``any``, ``unknown``
  or a ``Record``) -- found by a preview;
- every type a tagged function refers to is mapped (string -> text, number -> double, bigint ->
  bigint, boolean -> boolean, Date -> timestamp, ``T | null`` / ``T | undefined`` / an optional
  field -> nullable ``T``, arrays -> lists, interfaces and object types -> named object types, a
  union of string literals -> an enum, ``any`` / ``unknown`` / ``Record`` -> json), and one that
  cannot be mapped is a problem named by where it is used.

Every problem is collected, and the bundle is refused with all of them at once.
"""

# Requirements: REQ-1984
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from provisa.codesource.bundle import BundleRefused

TABLE, COMMAND, STREAM = "table", "command", "stream"
PROVISA_TAGS = frozenset({TABLE, COMMAND, STREAM})

#: The standard JSDoc and TSDoc tags an export may carry beside Provisa's. Any other is unknown.
STANDARD_TAGS = frozenset(
    {
        "param", "arg", "argument", "returns", "return", "example", "deprecated", "see",
        "since", "throws", "exception", "remarks", "privateRemarks", "link", "linkcode",
        "linkplain", "typeParam", "template", "type", "typedef", "property", "prop", "author",
        "internal", "beta", "alpha", "experimental", "public", "private", "protected", "readonly",
        "default", "defaultValue", "override", "virtual", "sealed", "packageDocumentation",
        "inheritDoc", "label", "summary", "description", "desc", "async", "function", "func",
        "method", "file", "fileoverview", "module", "version", "license", "copyright", "ignore",
        "todo", "callback", "constant", "const", "abstract", "access", "category",
    }
)  # fmt: skip


# -- shapes -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scalar:
    #: The IR type: text, double, bigint, boolean, timestamp or json.
    ir: str


@dataclass(frozen=True)
class ListOf:
    element: "Shape"


@dataclass(frozen=True)
class Named:
    """A named object type, in :attr:`Manifest.types`."""

    name: str


@dataclass(frozen=True)
class Anonymous:
    """An object type with no name of its own (``{ ok: boolean }``)."""

    fields: tuple["Field", ...]


@dataclass(frozen=True)
class EnumOf:
    #: The union's alias name, or None for an inline union.
    name: str | None
    values: tuple[str, ...]


Shape = Scalar | ListOf | Named | Anonymous | EnumOf

#: Loose: a value of any shape, served as json (and, as a row type, typed by a preview).
LOOSE = Scalar("json")


@dataclass(frozen=True)
class Field:
    name: str
    shape: Shape
    nullable: bool


@dataclass(frozen=True)
class ObjectType:
    name: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Parameter:
    name: str
    shape: Shape
    nullable: bool
    #: A non-optional parameter is required by the source (REQ-1986's native_filter_required).
    required: bool


@dataclass(frozen=True)
class Export:
    name: str
    kind: str
    description: str
    parameters: tuple[Parameter, ...]
    #: A table's or stream's row type; a command's result (None: it returns nothing).
    returns: Shape | None
    #: Whether the columns are found by a preview: the row type is loose.
    preview: bool = False
    #: A command's result: rows (a collection) or one value.
    many: bool = False


@dataclass(frozen=True)
class Manifest:
    exports: tuple[Export, ...]
    types: dict[str, ObjectType]

    def export(self, name: str) -> Export:
        return next(e for e in self.exports if e.name == name)


class ManifestRefused(BundleRefused):
    """A bundle whose declarations break a rule: every problem, each by name."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(
            "manifest_refused",
            "the bundle's declarations cannot be used: " + "; ".join(problems),
            problems="; ".join(problems),
        )
        self.problems = problems


# -- mapping ----------------------------------------------------------------------------------------


class _Mapper:
    def __init__(self, raw_types: dict[str, Any]) -> None:
        self.raw_types = raw_types
        self.types: dict[str, ObjectType] = {}
        self.problems: list[str] = []
        self._mapping: set[str] = set()

    def fail(self, where: str, reason: str) -> Shape:
        self.problems.append(f"{where}: {reason}")
        return LOOSE

    def shape(self, node: dict, where: str) -> tuple[Shape, bool]:
        """``node``'s shape and whether it is nullable."""
        kind = node["kind"]
        if kind == "union":
            present = [m for m in node["members"] if m["kind"] not in ("undefined", "null")]
            nullable = len(present) != len(node["members"])
            kinds = {m["kind"] for m in present}
            if kinds == {"boolean"}:
                return Scalar("boolean"), nullable
            if (
                present
                and kinds == {"literal"}
                and all(isinstance(m["value"], str) for m in present)
            ):
                return EnumOf(node.get("name"), tuple(m["value"] for m in present)), nullable
            if len(present) == 1:
                inner, inner_nullable = self.shape(present[0], where)
                return inner, nullable or inner_nullable
            return self.fail(
                where, f"a union of {', '.join(sorted(kinds))} cannot be mapped"
            ), nullable
        return self._single(node, where), False

    def _single(self, node: dict, where: str) -> Shape:
        kind = node["kind"]
        simple = {
            "string": "text",
            "number": "double",
            "bigint": "bigint",
            "boolean": "boolean",
            "date": "timestamp",
        }
        if kind in simple:
            return Scalar(simple[kind])
        if kind in ("any", "unknown", "record"):
            return LOOSE
        if kind == "literal":
            if isinstance(node["value"], str):
                return EnumOf(None, (node["value"],))
            return Scalar("double")
        if kind == "array":
            element, _ = self.shape(node["element"], f"{where}[]")
            return ListOf(element)
        if kind == "ref":
            self._named(node["name"])
            return Named(node["name"])
        if kind == "object":
            return Anonymous(self._fields(node["fields"], where))
        if kind in ("promise", "iterable"):
            return self.fail(where, "a Promise or an iterable is a function's result only")
        text = node.get("text", kind)
        return self.fail(where, f"the type {text} cannot be mapped")

    def _fields(self, fields: list[dict], owner: str) -> tuple[Field, ...]:
        out = []
        for f in fields:
            shape, nullable = self.shape(f["type"], f"{owner}.{f['name']}")
            out.append(Field(f["name"], shape, nullable or f["optional"]))
        return tuple(out)

    def _named(self, name: str) -> None:
        if name in self.types or name in self._mapping:
            return
        self._mapping.add(name)
        raw = self.raw_types[name]
        self.types[name] = ObjectType(name, self._fields(raw["fields"], name))
        self._mapping.discard(name)


def _unwrap_promise(node: dict) -> dict:
    return node["value"] if node["kind"] == "promise" else node


def _rows(mapper: _Mapper, export: str, element: dict) -> tuple[Shape, bool]:
    """The row type of a table or stream, and whether its columns come from a preview."""
    if element["kind"] in ("any", "unknown", "record"):
        return LOOSE, True
    shape, _ = mapper.shape(element, f"{export} (row)")
    if not isinstance(shape, (Named, Anonymous)):
        mapper.fail(export, "its rows are not objects; a row is an object whose fields are columns")
    return shape, False


def read_manifest(raw: dict) -> Manifest:
    """The bundle's tables, commands and streams, from the reader's output; refused with every
    problem when any rule is broken."""
    mapper = _Mapper(raw.get("types", {}))
    problems = mapper.problems
    for diagnostic in raw.get("diagnostics", []):
        problems.append(f"the declarations do not type-check: {diagnostic}")
    exports: list[Export] = []
    for entry in raw["exports"]:
        name, tags = entry["name"], entry["tags"]
        for tag in tags:
            if tag not in PROVISA_TAGS and tag not in STANDARD_TAGS:
                problems.append(f"{name}: unknown tag @{tag}")
        kinds = sorted(PROVISA_TAGS.intersection(tags))
        if not kinds:
            continue  # untagged: ignored
        if len(kinds) > 1:
            problems.append(f"{name}: tagged {', '.join('@' + k for k in kinds)}; an export is one")
            continue
        kind = kinds[0]
        signatures = entry["signatures"]
        if len(signatures) != 1:
            problems.append(
                f"{name}: @{kind} needs one function signature, it has {len(signatures)}"
            )
            continue
        (signature,) = signatures
        parameters = []
        for p in signature["parameters"]:
            if p["rest"]:
                problems.append(f"{name}: the rest parameter {p['name']} cannot be a parameter")
                continue
            shape, nullable = mapper.shape(p["type"], f"{name}({p['name']})")
            parameters.append(Parameter(p["name"], shape, nullable, required=not p["optional"]))
        returns = signature["returns"]
        if kind == TABLE:
            result = _unwrap_promise(returns)
            if result["kind"] == "array":
                element = result["element"]
            elif result["kind"] == "iterable":
                element = result["element"]
            else:
                problems.append(f"{name}: @table returns a single value, not a collection of rows")
                continue
            row, preview = _rows(mapper, name, element)
            exports.append(
                Export(name, kind, entry["description"], tuple(parameters), row, preview)
            )
        elif kind == STREAM:
            if not (returns["kind"] == "iterable" and returns["async"]):
                problems.append(
                    f"{name}: @stream is an async generator (returns AsyncGenerator<T>)"
                )
                continue
            row, preview = _rows(mapper, name, returns["element"])
            exports.append(
                Export(name, kind, entry["description"], tuple(parameters), row, preview)
            )
        else:
            result = _unwrap_promise(returns)
            if result["kind"] == "undefined":
                shape, many = None, False
            elif result["kind"] in ("array", "iterable"):
                shape, _ = mapper.shape(result["element"], f"{name} (result)")
                many = True
            else:
                shape, _ = mapper.shape(result, f"{name} (result)")
                many = False
            exports.append(
                Export(name, kind, entry["description"], tuple(parameters), shape, many=many)
            )
    if problems:
        raise ManifestRefused(problems)
    return Manifest(tuple(exports), mapper.types)
