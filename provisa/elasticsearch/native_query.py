# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An Elasticsearch table registered from a native search (REQ-2017).

The table's ``query_template`` holds one JSON document, ``{"index": ..., "query": {...}}``, the
Query DSL of an ``_search`` request, optionally with ``aggs``, ``sort`` and ``highlight``. An
argument is a placeholder string value ``"{{name}}"`` anywhere in the request, and a parameter of
the table (``query_arg``, REQ-1986). Binding replaces each placeholder node of the parsed request
with the argument's JSON value: a value is never written into the request's text, so it can only
ever be a value. The table only reads: the request is sent to ``_search`` and nowhere else, and
the keys that would page it or name another endpoint are refused.

A request with ``aggs`` answers one row per bucket (nested buckets flattened, one column per key
and metric); one without answers one row per hit.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

QUERY_ARG = "query_arg"
_PLACEHOLDER = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_EMBEDDED = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")
# What a native search may hold beside its index. Paging (from, search_after, pit, scroll) is the
# reader's own: the whole answer is read.
_SEARCH_KEYS = frozenset(
    {
        "query",
        "aggs",
        "aggregations",
        "sort",
        "highlight",
        "_source",
        "size",
        "min_score",
        "runtime_mappings",
    }
)
# A bucket's own keys; any other dict in it is a sub-aggregation.
_BUCKET_KEYS = frozenset(
    {"key", "key_as_string", "doc_count", "from", "from_as_string", "to", "to_as_string"}
)
_NAME = re.compile(r"[^A-Za-z0-9_]+")


class NativeSearchRefused(ValueError):
    """A native search that cannot be registered or run, said naming what is wrong."""

    code = "schema.elasticsearch_native_query_invalid"

    def __init__(self, table: str, reason: str) -> None:
        self.params = {"table": table, "reason": reason}
        super().__init__(f"Table {table!r}: {reason}")


@dataclass(frozen=True)
class NativeSearch:
    index: str
    body: dict  # the _search request, its arguments still "{{name}}"

    @property
    def buckets(self) -> bool:
        """Whether the search answers buckets (its aggregations) rather than hits."""
        return bool(self.body.get("aggs") or self.body.get("aggregations"))


def parse(table: str, text: str) -> NativeSearch:
    """The stored native search of ``table``: its index and its ``_search`` request."""
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise NativeSearchRefused(table, f"the native query is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise NativeSearchRefused(table, 'the native query is {"index": ..., "query": {...}}')
    index = doc.get("index")
    if not isinstance(index, str) or not index.strip():
        raise NativeSearchRefused(table, "the native query names its index")
    if index.startswith("_") or "/" in index or _EMBEDDED.search(index):
        # An index named "_delete_by_query", or a path, would reach another endpoint.
        raise NativeSearchRefused(
            table, f"the index {index!r} is an index name; a native query only searches"
        )
    body = {k: v for k, v in doc.items() if k != "index"}
    unknown = sorted(set(body) - _SEARCH_KEYS)
    if unknown:
        raise NativeSearchRefused(
            table,
            f"a native query is a search ({', '.join(sorted(_SEARCH_KEYS))}), not {unknown}",
        )
    if "query" not in body and not (body.get("aggs") or body.get("aggregations")):
        raise NativeSearchRefused(table, "the native query holds a query or aggregations")
    size = body.get("size")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        raise NativeSearchRefused(table, "size is the most rows the search answers, a number")
    return NativeSearch(index, body)


def _walk(node: Any, path: str):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield f"{path}[{i}]", value
            yield from _walk(value, f"{path}[{i}]")


def placeholders(table: str, search: NativeSearch) -> set[str]:
    """The arguments ``search`` names. A placeholder inside a longer string is refused: it could
    only be filled by writing a value into text."""
    found: set[str] = set()
    for path, value in _walk(search.body, "search"):
        if isinstance(value, str):
            whole = _PLACEHOLDER.match(value)
            if whole:
                found.add(whole.group(1))
            elif _EMBEDDED.search(value):
                raise NativeSearchRefused(
                    table,
                    f"the placeholder in {value!r} at {path} is inside a longer string; an "
                    "argument is a whole value",
                )
    return found


def check(table: str, text: str, arguments: set[str]) -> NativeSearch:
    """``text`` parsed and checked against the table's declared arguments (its ``query_arg``
    parameters, by name): each placeholder names one, and each one is used."""
    search = parse(table, text)
    named = placeholders(table, search)
    undeclared = sorted(named - arguments)
    if undeclared:
        raise NativeSearchRefused(
            table, f"the search names {undeclared}, which the table declares as no argument"
        )
    unused = sorted(arguments - named)
    if unused:
        raise NativeSearchRefused(table, f"the arguments {unused} appear nowhere in the search")
    return search


def bind(search: NativeSearch, values: dict[str, Any]) -> dict:
    """The request with each placeholder replaced by its argument's JSON value (``values`` maps
    an argument's name to its converted value). An argument with no value binds null."""
    from provisa.cosmosdb.table import json_value

    def fill(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str):
            whole = _PLACEHOLDER.match(node)
            if whole:
                return json_value(values[whole.group(1)])
        return node

    return fill(copy.deepcopy(search.body))


def column_name(name: str) -> str:
    """An aggregation, key or field name as a column name."""
    return _NAME.sub("_", name).strip("_") or "value"


def _metric(name: str, result: dict) -> dict[str, Any]:
    """One metric aggregation's columns: a single value under its name; several (stats,
    percentiles, extended_stats) each under ``name_<part>``; anything else as JSON."""
    if "value" in result and set(result) <= {"value", "value_as_string", "meta"}:
        return {column_name(name): result.get("value_as_string", result["value"])}
    if isinstance(result.get("values"), dict):  # percentiles, percentile_ranks
        return {column_name(f"{name}_{k}"): v for k, v in result["values"].items()}
    scalars = {
        k: v
        for k, v in result.items()
        if k != "meta" and (v is None or isinstance(v, (int, float, str, bool)))
    }
    if scalars and len(scalars) == len([k for k in result if k != "meta"]):
        return {column_name(f"{name}_{k}"): v for k, v in scalars.items()}
    return {column_name(name): result}


def _buckets(result: dict) -> list[dict]:
    """A bucket aggregation's buckets as a list; a keyed one (filters, keyed ranges) gives each
    bucket its key."""
    buckets = result["buckets"]
    if isinstance(buckets, dict):
        return [{"key": key, **bucket} for key, bucket in buckets.items()]
    return list(buckets)


def flatten_buckets(table: str, aggregations: dict) -> list[dict]:
    """An aggregations response as rows: one per innermost bucket, each carrying its key (and
    its doc count) at every level and the metrics beside it. A level holds one bucket
    aggregation at most -- two would answer two unrelated sets of rows."""

    def level(aggs: dict, prefix: dict) -> list[dict]:
        bucketed = {k: v for k, v in aggs.items() if isinstance(v, dict) and "buckets" in v}
        if len(bucketed) > 1:
            raise NativeSearchRefused(
                table,
                f"the aggregations {sorted(bucketed)} are bucket aggregations side by side; a "
                "level of a table's aggregations holds one, nested ones below it",
            )
        row = dict(prefix)
        for name, result in aggs.items():
            if name not in bucketed and isinstance(result, dict):
                row.update(_metric(name, result))
        if not bucketed:
            return [row]
        ((name, result),) = bucketed.items()
        rows: list[dict] = []
        for bucket in _buckets(result):
            key = bucket.get("key_as_string", bucket.get("key"))
            here = {**row, f"{column_name(name)}_doc_count": bucket.get("doc_count")}
            if isinstance(key, dict):  # a composite aggregation's key: one column per source
                here.update({column_name(f"{name}_{k}"): v for k, v in key.items()})
            else:
                here[column_name(name)] = key
            sub = {k: v for k, v in bucket.items() if k not in _BUCKET_KEYS and isinstance(v, dict)}
            rows.extend(level(sub, here))
        return rows

    return level(aggregations, {})


def hit_document(hit: dict) -> dict:
    """One hit as the document a row is read from: its ``_source``, its ``_id`` and ``_score``,
    and each highlighted field's fragments under ``highlight_<field>``."""
    doc = dict(hit.get("_source") or {})
    doc["_id"] = hit.get("_id")
    doc["_score"] = hit.get("_score")
    for field, fragments in (hit.get("highlight") or {}).items():
        doc[f"highlight_{column_name(field)}"] = fragments
    return doc


def check_table(table: Any) -> NativeSearch:
    """A native-search table as registered (a ``core.models.Table``): its search checked against
    its arguments, every column typed, and none of the settings a search cannot take."""
    name = table.table_name
    arguments = {
        c.name.removeprefix("_nf_") for c in table.columns if c.native_filter_type == QUERY_ARG
    }
    other = sorted(
        {c.native_filter_type for c in table.columns if c.native_filter_type} - {QUERY_ARG}
    )
    if other:
        raise NativeSearchRefused(name, f"a native search's parameters are query_arg, not {other}")
    untyped = [c.name for c in table.columns if not c.data_type]
    if untyped:
        raise NativeSearchRefused(name, f"the columns {untyped} have no data type")
    if table.change_signal == "native":
        raise NativeSearchRefused(name, "a search's answer has no change feed; use a TTL")
    if table.row_materialize:
        raise NativeSearchRefused(name, "a search's rows have no key to be fetched by")
    return check(name, table.query_template, arguments)
