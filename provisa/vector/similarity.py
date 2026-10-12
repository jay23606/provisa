# Copyright (c) 2026 Kenneth Stott
# Canary: 0fb5b3a2-a7ca-4851-8b8d-efedfaf93483
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""``cosine_similarity(column, query)`` through the one query pipeline (REQ-423, REQ-426,
REQ-429, REQ-430, REQ-652).

A statement writes ``cosine_similarity(<embedding column>, <query>)``; ``<query>`` is a vector
(a bound parameter, or a ``'[…]'`` literal), a text (embedded with the column's model), or
another embedding column of the same model. The call goes through the pipeline's stages:

1. governed with the whole statement (:func:`govern_calls`, from ``stage2._govern_select``): its
   column must be an embedding column (REQ-421) the role is served — visibility and scope, a
   ``restricted`` scope being the sensitivity tier (REQ-426/652) — and the call is completed with
   the column's model and dimensions, as ``cosine_similarity(col, query, '<model>', <dims>)``;
2. its text literals embedded, once per governed statement (:func:`embed_text_queries`);
3. its bound query values made vectors of the model's dimensions, per execution
   (:func:`bind_query_vectors`) — a vector always travels as a bound value, as JSON text;
4. lowered to the terminal that runs it, after the dialect transpile (:func:`lower`).

Row filters and domain rules apply to the statement as to any other: a row the role cannot read
is never scored.
"""

# Requirements: REQ-423, REQ-426, REQ-429, REQ-430, REQ-652

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlglot
import sqlglot.expressions as exp

FUNCTION = "cosine_similarity"
# A governed call's distance (1 - similarity), written where a top-k search reads a replica's
# index (:func:`index_top_k`): an index serves nearest-first by distance, not by similarity.
DISTANCE = "provisa_cosine_distance"
# The governed form: column, query, model id, dimensions.
_GOVERNED_ARITY = 4

#: Source dialects whose own SQL computes the call, so a statement may run there (DIRECT).
DIRECT_DIALECTS = frozenset({"postgres", "snowflake"})


class SimilarityRefused(ValueError):
    """A ``cosine_similarity`` call the statement may not make, said naming what is wrong."""


class SimilarityNotPermitted(PermissionError):
    """The role may not search the embedding column the call names (REQ-426)."""


def is_call(node: exp.Expr) -> bool:  # pyright: ignore[reportPrivateImportUsage]
    return isinstance(node, exp.Anonymous) and node.name.lower() == FUNCTION


def _is_distance(node: exp.Expr) -> bool:  # pyright: ignore[reportPrivateImportUsage]
    return isinstance(node, exp.Anonymous) and node.name.lower() == DISTANCE


def mentions(sql: str) -> bool:
    """Whether ``sql`` may hold a call — a cheap check before parsing."""
    lowered = sql.lower()
    return FUNCTION in lowered or DISTANCE in lowered


def _vector_text(values: Sequence[Any]) -> str:
    return json.dumps([float(v) for v in values])


def _parsed_vector(text: str) -> list[float] | None:
    """The vector a text spells (``'[0.1, 0.2]'``), or None when it is not one."""
    stripped = text.strip()
    if not stripped.startswith("["):
        return None
    try:
        values = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(values, list) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in values
    ):
        return None
    return [float(v) for v in values]


def _check_dimensions(vector: Sequence[float], model: str, dims: int) -> None:  # REQ-429
    if len(vector) != dims:
        raise SimilarityRefused(
            f"the query vector has {len(vector)} dimensions; the column's model {model!r} has "
            f"{dims}"
        )


# --------------------------------------------------------------------------------------------- #
# 1. Governance                                                                                 #
# --------------------------------------------------------------------------------------------- #


def _embedding_of(
    col: exp.Expr,  # pyright: ignore[reportPrivateImportUsage]
    alias_to_tid: dict[str, int],
    embedding_columns: dict[int, dict[str, str]],
) -> tuple[int, str]:
    """(table id, model id) of the embedding column ``col`` names; refused when it names none."""
    if not isinstance(col, exp.Column):
        raise SimilarityRefused(
            f"cosine_similarity's first argument must be an embedding column, not {col.sql()!r}"
        )
    if col.table:
        tid = alias_to_tid.get(col.table)
        candidates = [tid] if tid is not None else []
    else:
        candidates = [t for t in alias_to_tid.values() if col.name in embedding_columns.get(t, {})]
    found = [(t, embedding_columns.get(t, {}).get(col.name)) for t in candidates]
    found = [(t, m) for t, m in found if m is not None]
    if len(found) != 1:
        raise SimilarityRefused(f"{col.sql()!r} is not an embedding column of this statement")
    return found[0]  # pyright: ignore[reportReturnType]


def govern_calls(
    select: exp.Select,
    alias_to_tid: dict[str, int],
    embedding_columns: dict[int, dict[str, str]],
    embedding_dims: dict[str, int],
    is_visible: Callable[[exp.Column], bool],
    role_id: str,
) -> None:  # REQ-423, REQ-426, REQ-429, REQ-652
    """Govern, in place, each call of ``select`` (not of a nested SELECT): its column is an
    embedding column the role is served, and the call is completed with the column's model and
    dimensions. A call already governed (a later pass over the same statement) is left alone."""
    for call in list(select.find_all(exp.Anonymous)):
        if not is_call(call) or call.find_ancestor(exp.Select) is not select:
            continue
        args = list(call.expressions)
        if len(args) == _GOVERNED_ARITY:
            continue
        if len(args) != 2:
            raise SimilarityRefused(
                "cosine_similarity takes an embedding column and a query (a vector, a text or "
                f"another embedding column); it was given {len(args)} arguments"
            )
        col, query = args
        _, model = _embedding_of(col, alias_to_tid, embedding_columns)
        for searched in (col, query):
            if isinstance(searched, exp.Column) and not is_visible(searched):
                raise SimilarityNotPermitted(
                    f"role {role_id!r} may not search embedding column {searched.sql()!r}"
                )
        if model not in embedding_dims:
            raise SimilarityRefused(
                f"the embedding model {model!r} of column {col.sql()!r} is not registered"
            )
        dims = embedding_dims[model]
        if isinstance(query, exp.Column):
            _, query_model = _embedding_of(query, alias_to_tid, embedding_columns)
            if query_model != model:
                raise SimilarityRefused(
                    f"{col.sql()!r} is embedded by {model!r} and {query.sql()!r} by "
                    f"{query_model!r}; their vectors cannot be compared"
                )
        elif isinstance(query, exp.Literal) and query.is_string:
            vector = _parsed_vector(query.this)
            if vector is not None:
                _check_dimensions(vector, model, dims)
                query = exp.Literal.string(_vector_text(vector))
        elif not isinstance(query, exp.Parameter):
            raise SimilarityRefused(
                "cosine_similarity's query is a vector ('[…]' or a bound value), a text, or an "
                f"embedding column, not {query.sql()!r}"
            )
        call.set(
            "expressions",
            [col, query, exp.Literal.string(model), exp.Literal.number(dims)],
        )


def _governed_calls(tree: exp.Expr) -> list[exp.Anonymous]:  # pyright: ignore[reportPrivateImportUsage]
    calls = [n for n in tree.find_all(exp.Anonymous) if is_call(n)]
    for call in calls:
        if len(call.expressions) != _GOVERNED_ARITY:
            raise SimilarityRefused("cosine_similarity was not governed")
    return calls


# --------------------------------------------------------------------------------------------- #
# 2–3. Query vectors                                                                            #
# --------------------------------------------------------------------------------------------- #


async def _embed(text: str, model_id: str, registry: Any, provider: Any) -> list[float]:
    from provisa.vector.query import vectorize_text

    return await vectorize_text(text, registry.get(model_id), provider)


async def embed_text_queries(governed_sql: str, registry: Any, provider: Any = None) -> str:
    """``governed_sql`` with each text literal query embedded by its column's model (REQ-430).
    The text is part of the statement, so the vector is too: it is kept with the governed
    statement."""
    if not mentions(governed_sql):
        return governed_sql
    tree = sqlglot.parse_one(governed_sql, read="postgres")
    changed = False
    for call in _governed_calls(tree):
        col, query, model, dims = call.expressions
        if not (isinstance(query, exp.Literal) and query.is_string):
            continue
        if _parsed_vector(query.this) is not None:
            continue
        vector = await _embed(query.this, model.this, registry, provider)
        _check_dimensions(vector, model.this, int(dims.this))
        call.set("expressions", [col, exp.Literal.string(_vector_text(vector)), model, dims])
        changed = True
    return tree.sql(dialect="postgres") if changed else governed_sql


async def bind_query_vectors(
    governed_sql: str, params: list[Any] | None, registry: Any, provider: Any = None
) -> list[Any] | None:
    """``params`` with each value a call takes as its query made a vector of the column's model,
    as JSON text: a list of numbers, a text spelling one, or a text to embed (REQ-429, REQ-430).
    Run per execution: the values are the request's."""
    if not params or not mentions(governed_sql):
        return params
    tree = sqlglot.parse_one(governed_sql, read="postgres")
    bound = list(params)
    for call in _governed_calls(tree):
        _, query, model, dims = call.expressions
        if not isinstance(query, exp.Parameter):
            continue
        index = int(query.this.this) - 1
        value = bound[index]
        if isinstance(value, (list, tuple)):
            vector = [float(v) for v in value]
        elif isinstance(value, str):
            parsed = _parsed_vector(value)
            vector = (
                parsed
                if parsed is not None
                else await _embed(value, model.this, registry, provider)
            )
        else:
            raise SimilarityRefused(
                f"cosine_similarity's query value must be a vector or a text, not {value!r}"
            )
        _check_dimensions(vector, model.this, int(dims.this))
        bound[index] = _vector_text(vector)
    return bound


# --------------------------------------------------------------------------------------------- #
# 4. Lowering                                                                                   #
# --------------------------------------------------------------------------------------------- #

# Plain PostgreSQL, no extension: the cosine of two float8 arrays. The query is JSON text
# ('[…]'), which PostgreSQL's array syntax spells with braces.
_PG_PLAIN = (
    "(SELECT SUM(_a * _b) / (SQRT(SUM(_a * _a)) * SQRT(SUM(_b * _b))) "
    "FROM UNNEST(CAST({col} AS DOUBLE PRECISION[]), "
    "CAST(TRANSLATE(CAST({query} AS TEXT), '[]', '{{}}') AS DOUBLE PRECISION[])) "
    "AS _provisa_v(_a, _b))"
)


def _lowered_distance(call: exp.Anonymous, dialect: str, pgvector: bool) -> exp.Expr:  # pyright: ignore[reportPrivateImportUsage]
    """A governed distance in the form a replica's index serves (REQ-424): DuckDB's
    ``array_cosine_distance`` and pgvector's ``<=>``; elsewhere one minus the similarity."""
    col, query, _, dims = call.expressions
    if dialect == "duckdb":
        vector_type = exp.DataType.build(f"FLOAT[{int(dims.this)}]", dialect=dialect)
        return exp.Anonymous(
            this="array_cosine_distance",
            expressions=[exp.Cast(this=n.copy(), to=vector_type.copy()) for n in (col, query)],
        )
    if dialect == "postgres" and pgvector:
        # The cast a replica's index is built on (replica_target._pg_index_vectors).
        vector = exp.DataType.build(f"vector({int(dims.this)})", udt=True)
        return exp.Paren(
            this=exp.Operator(
                this=exp.Cast(this=col.copy(), to=vector.copy()),
                operator="<=>",
                expression=exp.Cast(this=query.copy(), to=vector.copy()),
            )
        )
    similarity = exp.Anonymous(this=FUNCTION, expressions=[e.copy() for e in call.expressions])
    return exp.Paren(
        this=exp.Sub(this=exp.Literal.number(1), expression=_lowered(similarity, dialect, pgvector))
    )


def _lowered(call: exp.Anonymous, dialect: str, pgvector: bool) -> exp.Expr:  # pyright: ignore[reportPrivateImportUsage]
    if _is_distance(call):
        return _lowered_distance(call, dialect, pgvector)
    col, query, _, dims = call.expressions
    d = int(dims.this)

    def cast(node: exp.Expr, type_sql: str) -> exp.Cast:  # pyright: ignore[reportPrivateImportUsage]
        return exp.Cast(this=node.copy(), to=exp.DataType.build(type_sql, dialect=dialect))

    if dialect == "duckdb":
        return exp.Anonymous(
            this="array_cosine_similarity",
            expressions=[cast(col, f"FLOAT[{d}]"), cast(query, f"FLOAT[{d}]")],
        )
    if dialect == "trino":
        return exp.Anonymous(
            this="cosine_similarity",
            expressions=[
                cast(col, "ARRAY(DOUBLE)"),
                cast(exp.Anonymous(this="json_parse", expressions=[query.copy()]), "ARRAY(DOUBLE)"),
            ],
        )
    if dialect == "snowflake":
        vector_type = f"VECTOR(FLOAT, {d})"
        return exp.Anonymous(
            this="VECTOR_COSINE_SIMILARITY",
            expressions=[cast(col, vector_type), cast(query, vector_type)],
        )
    if dialect == "postgres":
        if pgvector:
            vector = exp.DataType.build("vector", udt=True)
            distance = exp.Anonymous(
                this="cosine_distance",
                expressions=[exp.Cast(this=node.copy(), to=vector.copy()) for node in (col, query)],
            )
            return exp.Paren(this=exp.Sub(this=exp.Literal.number(1), expression=distance))
        return sqlglot.parse_one(
            _PG_PLAIN.format(col=col.sql(dialect="postgres"), query=query.sql(dialect="postgres")),
            read="postgres",
        )
    raise SimilarityRefused(f"cosine_similarity cannot be computed in {dialect} SQL")


def lower(sql: str, dialect: str, *, pgvector: bool = False) -> str:  # REQ-423
    """``sql`` (already in ``dialect``) with each governed call written in that dialect's own
    form: DuckDB ``array_cosine_similarity``, Trino ``cosine_similarity`` over arrays, Snowflake
    ``VECTOR_COSINE_SIMILARITY``, PostgreSQL pgvector's ``cosine_distance`` where the source has
    the extension (``pgvector``) and a plain array computation where it has not."""
    if not mentions(sql):
        return sql
    tree = sqlglot.parse_one(sql, read=dialect)
    calls = _governed_calls(tree) + [n for n in tree.find_all(exp.Anonymous) if _is_distance(n)]
    if not calls:
        return sql
    for call in calls:
        call.replace(_lowered(call, dialect, pgvector))
    return tree.sql(dialect=dialect)


# --------------------------------------------------------------------------------------------- #
# A replica's index (REQ-424)                                                                   #
# --------------------------------------------------------------------------------------------- #


def _tables_of(select: exp.Select) -> list[exp.Table]:  # pyright: ignore[reportPrivateImportUsage]
    from_ = select.args.get("from_") or select.args.get("from")
    sources = [from_.this] if from_ is not None else []
    sources += [join.this for join in select.args.get("joins") or []]
    return [t for t in sources if isinstance(t, exp.Table)]


def _column_table(column: exp.Expr, select: exp.Select) -> exp.Table | None:  # pyright: ignore[reportPrivateImportUsage]
    """The table of ``select`` that ``column`` reads, or None when it is not one of them."""
    if not isinstance(column, exp.Column):
        return None
    tables = _tables_of(select)
    if not column.table:
        return tables[0] if len(tables) == 1 else None
    for table in tables:
        if column.table in (table.alias_or_name, table.name):
            return table
    return None


def index_top_k(pg_sql: str, replicas: frozenset[tuple[str | None, str, str]]) -> tuple[str, bool]:
    """``pg_sql`` with each top-k search over a replica written nearest-first by distance, the
    order a replica's HNSW index serves (REQ-424), and whether there was one.

    A top-k search is a SELECT with a LIMIT ordered first by a governed call, most similar first,
    whose embedding column is a column of a table read at its replica's address (``replicas``,
    as ``(catalog, schema, table)``). The index answers it approximately: the caller says so in
    the statement's warnings (:func:`approximate_index_warning`). Every other ordering is left as
    it is, and computed exactly."""
    if not replicas or not mentions(pg_sql):
        return pg_sql, False
    tree = sqlglot.parse_one(pg_sql, read="postgres")
    searched = False
    for select in tree.find_all(exp.Select):
        order = select.args.get("order")
        if select.args.get("limit") is None or order is None or not order.expressions:
            continue
        first = order.expressions[0]
        call = first.this
        if not (first.args.get("desc") and is_call(call)):
            continue
        if len(call.expressions) != _GOVERNED_ARITY:
            raise SimilarityRefused("cosine_similarity was not governed")
        table = _column_table(call.expressions[0], select)
        if table is None or (table.catalog or None, table.db, table.name) not in replicas:
            continue
        distance = exp.Anonymous(this=DISTANCE, expressions=[e.copy() for e in call.expressions])
        first.replace(exp.Ordered(this=distance, desc=False))
        searched = True
    return (tree.sql(dialect="postgres"), True) if searched else (pg_sql, False)


def approximate_index_warning() -> Any:
    """What an answer read through a replica's vector index says about itself (REQ-424)."""
    from provisa.core.statement_warnings import ServerWarning

    return ServerWarning(
        code="statement.approximate_index",
        message=(
            "The most similar rows were found through an approximate vector index: a row "
            "slightly more similar than the last one returned may be missing."
        ),
    )
