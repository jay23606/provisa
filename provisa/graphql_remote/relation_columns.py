# Copyright (c) 2026 Kenneth Stott
# Canary: 82d4d0d2-fb49-462a-b53a-8ae78e4d5057
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Which registered columns of a remote GraphQL table its readable relation holds.

A remote type's field that points at ONE object of another registered type is registered as a
column of its table, and is a relationship, not data: the rows read from the remote API do not
carry it (the related table is reached through the relationship, under its own governance). The
relation a statement reads -- the rows inlined into it, or the cache table they land in -- is
built without such columns. Whoever lists a table's columns in order to SELECT them names the same
set through this module, so a statement never asks the relation for a column it does not have.
"""

from __future__ import annotations

from typing import Any


def governed_types(sources: dict[str, Any]) -> set[str]:
    """The remote GraphQL type names that are registered tables, over every remote source."""
    return {
        tbl["gql_type_name"]
        for reg in sources.values()
        for tbl in reg.get("tables", [])
        if tbl.get("gql_type_name")
    }


def reference_columns(table: dict[str, Any], governed: set[str]) -> set[str]:
    """The names of ``table``'s registered columns that its relation does not hold: each points
    at one object of a registered type."""
    return {
        c["name"]
        for c in table.get("columns", [])
        if c.get("gql_object_type")
        and not c.get("gql_is_list", False)
        and c["gql_object_type"] in governed
    }


def columns_outside_relation(sources: dict[str, Any], source_id: str, table_name: str) -> set[str]:
    """The registered columns of ``source_id``'s table ``table_name`` (its SQL name) that its
    relation does not hold; none for a table that is not a remote GraphQL table. ``sources`` is
    keyed by source id."""
    reg = sources.get(source_id)
    if reg is None:
        return set()
    for tbl in reg.get("tables", []):
        if tbl["sql_name"] == table_name:
            return reference_columns(tbl, governed_types(sources))
    return set()
