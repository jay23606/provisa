# Copyright (c) 2026 Kenneth Stott
# Canary: b8d2f6a1-0e47-4c95-a3b7-1f6e9d0c4a85
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1965: GraphQL declares a column whose array depth is above 0 as a list, nested to that
depth, of the GraphQL type of its element -- from the hidden attributes alone, never from the
spelling of a source type -- and every other JSON column as the opaque JSON value."""

from __future__ import annotations

import pytest
from graphql import GraphQLList

from provisa.compiler.type_map import (
    BigInt,
    DateTime,
    GraphQLString,
    JSONScalar,
    column_type_to_graphql,
    nested_column_graphql_type,
)


def _column(native_type, depth=0, element=None):
    return {
        "column_name": "tags",
        "data_type": "json",
        "native_type": native_type,
        "array_depth": depth,
        "element_type": element,
    }


@pytest.mark.parametrize(
    "native_type",
    ["text[]", "varchar[]", "array(varchar)", "array(string)", "array<string>"],
)
def test_an_array_of_text_is_the_same_list_whichever_source_it_is_from(native_type):
    declared = nested_column_graphql_type(_column(native_type, 1, "text"))
    assert isinstance(declared, GraphQLList)
    assert declared.of_type is GraphQLString  # an element may be null


def test_a_nested_array_is_a_list_nested_to_its_depth():
    declared = nested_column_graphql_type(_column("bigint[][]", 2, "bigint"))
    assert isinstance(declared, GraphQLList) and isinstance(declared.of_type, GraphQLList)
    assert declared.of_type.of_type is BigInt


def test_the_element_is_the_graphql_type_of_its_semantic_type():
    declared = nested_column_graphql_type(_column("timestamptz[]", 1, "timestamp"))
    assert isinstance(declared, GraphQLList) and declared.of_type is DateTime


@pytest.mark.parametrize(
    "native_type",
    ["struct(a integer)", "map(varchar, integer)", "array(row(a integer))", "variant"],
)
def test_a_struct_a_map_or_an_array_of_structs_is_the_opaque_json_value(native_type):
    assert nested_column_graphql_type(_column(native_type)) is JSONScalar


def test_a_column_that_is_not_natively_nested_is_not_decided_here():
    assert nested_column_graphql_type({"column_name": "doc", "data_type": "json"}) is None
    assert nested_column_graphql_type({"column_name": "name", "data_type": "text"}) is None


@pytest.mark.parametrize(
    "spelling", ["array(varchar)", "varchar[]", "array<string>", "row(a integer)", "map(k, v)"]
)
def test_a_list_is_never_declared_from_the_spelling_of_a_source_type(spelling):
    """A column listed with a nested spelling and no attributes is JSON, as every surface lists
    it -- not a list on the engines whose spelling happens to be recognised."""
    assert column_type_to_graphql(spelling) is JSONScalar
