# Copyright (c) 2026 Kenneth Stott
# Canary: e08f233c-108f-4430-a313-9d40b5146490
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""``embed(model, text)``: the embedding of a text by a registered model (REQ-2002).

Provisa evaluates it; no source or engine ever sees the call. After governance
(:func:`fold`), each call is resolved:

* a literal text is embedded once, with the statement, and the call becomes the vector;
* a text read from rows -- a column or an expression -- is an item of the statement's select
  list: the item becomes the text, and once the rows are read (:func:`embed_rows`) each distinct
  text is embedded once and the column holds its vector. An ``embed()`` of rows anywhere else is
  refused by name: the rows it would need are not read there.

The model is a registered, enabled model (the registry allowlist); any other is refused naming it.
Every model a statement uses is recorded in its audit with its id, provider, dimensions and
version (``Folded.audit``).
"""

# Requirements: REQ-2002

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlglot
import sqlglot.expressions as exp

FUNCTION = "embed"
#: The result type of an embedded column: a list of floats.
VECTOR_TYPE = "real[]"


class EmbedRefused(ValueError):
    """An ``embed()`` call the statement may not make, said naming what is wrong."""


@dataclass(frozen=True)
class RowEmbed:
    """A select-list column whose texts are embedded once the rows are read."""

    position: int  # the column's place in the statement's output
    name: str
    model: str


@dataclass(frozen=True)
class Folded:
    """A governed statement with its ``embed()`` calls resolved."""

    sql: str
    rows: tuple[RowEmbed, ...] = ()
    # Each model the statement embeds with, in first use order, as its audit record names it:
    # id, provider, dimensions and version (providers.model_version). None: no embed() call.
    audit: tuple[dict[str, Any], ...] | None = None


def mentions(sql: str) -> bool:
    """Whether ``sql`` may hold a call -- a cheap check before parsing."""
    return f"{FUNCTION}(" in sql.lower().replace(" ", "")


def _calls(tree: exp.Expr) -> list[exp.Anonymous]:  # pyright: ignore[reportPrivateImportUsage]
    return [n for n in tree.find_all(exp.Anonymous) if n.name.lower() == FUNCTION]


def _output_select(tree: exp.Expr) -> exp.Select | None:  # pyright: ignore[reportPrivateImportUsage]
    """The SELECT whose list is the statement's output: the statement's own, or an INSERT's."""
    if isinstance(tree, exp.Select):
        return tree
    if isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Select):
        return tree.expression
    return None


def _model_arg(call: exp.Anonymous) -> str:
    if len(call.expressions) != 2:
        raise EmbedRefused(
            f"embed takes a model and a text; it was given {len(call.expressions)} arguments"
        )
    model = call.expressions[0]
    if not (isinstance(model, exp.Literal) and model.is_string):
        raise EmbedRefused(f"embed's model must be a model name in quotes, not {model.sql()}")
    return model.this


def _select_item(call: exp.Anonymous, output: exp.Select | None) -> tuple[int, str] | None:
    """The output column ``call`` is, when it is an item of the output select list itself."""
    if output is None:
        return None
    item: exp.Expr = call.parent if isinstance(call.parent, exp.Alias) else call  # pyright: ignore[reportPrivateImportUsage]
    for position, expression in enumerate(output.expressions):
        if expression is item:
            name = item.alias if isinstance(item, exp.Alias) else FUNCTION
            return position, name
    return None


def _vector_value(vector: Sequence[float]) -> exp.Expr:  # pyright: ignore[reportPrivateImportUsage]
    return exp.Cast(
        this=exp.Array(expressions=[exp.Literal.number(float(v)) for v in vector]),
        to=exp.DataType.build("REAL[]", dialect="postgres"),
    )


async def fold(governed_sql: str, registry: Any, provider_for: Any) -> Folded:  # REQ-2002
    """``governed_sql`` with each ``embed()`` call resolved (see the module docstring).
    ``provider_for(model)`` is the embedding provider of a registered model."""
    from provisa.vector.providers import model_version

    if not mentions(governed_sql):
        return Folded(governed_sql)
    tree = sqlglot.parse_one(governed_sql, read="postgres")
    calls = _calls(tree)
    if not calls:
        return Folded(governed_sql)
    output = _output_select(tree)
    rows: list[RowEmbed] = []
    models: list[str] = []
    for call in calls:
        model_id = _model_arg(call)
        model = registry.get(model_id)  # an unknown or disabled model is refused naming it
        if model_id not in models:
            models.append(model_id)
        text = call.expressions[1]
        if isinstance(text, exp.Literal) and text.is_string:
            (vector,) = await provider_for(model).embed([text.this], model)
            _check_dimensions(vector, model)
            call.replace(_vector_value(vector))
            continue
        item = _select_item(call, output)
        if item is None:
            raise EmbedRefused(
                f"embed({call.expressions[0].sql()}, {text.sql()}) embeds the text of rows, "
                "which Provisa embeds once they are read: write it as an item of the select list"
            )
        position, name = item
        rows.append(RowEmbed(position, name, model_id))
        replacement = text.copy()
        if isinstance(call.parent, exp.Alias):
            call.replace(replacement)
        else:
            call.replace(exp.Alias(this=replacement, alias=exp.to_identifier(name)))
    audit = []
    for model_id in models:
        model = registry.get(model_id)
        audit.append(
            {
                "id": model.id,
                "provider": model.provider,
                "dimensions": model.dimensions,
                "version": await model_version(model, provider_for(model)),
            }
        )
    return Folded(tree.sql(dialect="postgres"), tuple(rows), tuple(audit))


def _check_dimensions(vector: Sequence[float], model: Any) -> None:
    if len(vector) != model.dimensions:
        raise EmbedRefused(
            f"model {model.id!r} gave a vector of {len(vector)} dimensions; it is registered "
            f"with {model.dimensions}"
        )


async def embed_rows(result: Any, rows: Sequence[RowEmbed], registry: Any, provider_for: Any):
    """``result`` with each embedded column's texts replaced by their vectors, each distinct
    text embedded once per model. A NULL text has no embedding: it stays NULL."""
    from provisa.executor.result import QueryResult

    materialized = result.materialize()
    data = [list(r) for r in materialized.rows]
    types: list[str] | None = (
        None if materialized.column_types is None else list(materialized.column_types)
    )
    for spec in rows:
        model = registry.get(spec.model)
        texts = sorted({str(r[spec.position]) for r in data if r[spec.position] is not None})
        vectors = await provider_for(model).embed(texts, model) if texts else []
        if len(vectors) != len(texts):
            raise EmbedRefused(
                f"model {model.id!r} gave {len(vectors)} vectors for {len(texts)} texts"
            )
        for vector in vectors:
            _check_dimensions(vector, model)
        by_text = {t: [float(v) for v in vec] for t, vec in zip(texts, vectors)}
        for r in data:
            value = r[spec.position]
            r[spec.position] = None if value is None else by_text[str(value)]
        if types is not None:
            types[spec.position] = VECTOR_TYPE
    return QueryResult(
        rows=[tuple(r) for r in data],
        column_names=list(materialized.column_names),
        column_types=types,
        rowcount=materialized.rowcount,
    )
