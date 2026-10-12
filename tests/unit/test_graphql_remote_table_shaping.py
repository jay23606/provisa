# Copyright (c) 2026 Kenneth Stott
# Canary: c1a1e8de-8f7f-4e39-8f0f-0c6f5f8a2b31
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Unit tests for the graphql_remote registration shaping (REQ-1685).

Source coverage:
  - provisa/api/app_loaders.py — _graphql_remote_field_name, _build_graphql_remote_table

A `graphql_remote` source landed after boot must be queryable on its first query: the reload
builds each landed table's registration entry — its field name, its columns split from its
required call arguments, and its optional object-field shape — from exactly the rows the DB
loader reads. These two functions are that shaping, pulled out of the DB-coupled reload loop so
they are exercised directly rather than only through the live-endpoint integration test.
"""

import json

from provisa.api.app_loaders import _build_graphql_remote_table, _graphql_remote_field_name


class TestFieldName:
    def test_strips_the_domain_prefix_and_camel_cases_the_rest(self) -> None:
        assert _graphql_remote_field_name("sales__order_line_items") == "orderLineItems"

    def test_single_word_is_unchanged(self) -> None:
        assert _graphql_remote_field_name("sales__orders") == "orders"

    def test_no_domain_prefix_still_camel_cases(self) -> None:
        assert _graphql_remote_field_name("order_line_items") == "orderLineItems"


def _col(**overrides: object) -> dict:
    base = {
        "column_name": "id",
        "data_type": "text",
        "object_fields": None,
        "native_filter_type": None,
        "native_filter_required": None,
        "gql_selection": None,
        "gql_object_type": None,
        "gql_is_list": False,
    }
    base.update(overrides)
    return base


class TestBuildGraphqlRemoteTable:
    def test_shapes_name_and_source(self) -> None:
        tr = {"table_name": "sales__orders", "domain_id": "sales", "description": "Orders"}
        table = _build_graphql_remote_table(tr, [], "src-1")
        assert table["name"] == "sales__orders"
        assert table["sql_name"] == "sales__orders"
        assert table["field_name"] == "orders"
        assert table["source_id"] == "src-1"
        assert table["domain_id"] == "sales"
        assert table["description"] == "Orders"

    def test_missing_domain_id_defaults_to_empty_string(self) -> None:
        tr = {"table_name": "orders", "domain_id": None, "description": None}
        assert _build_graphql_remote_table(tr, [], "src-1")["domain_id"] == ""

    def test_argument_columns_become_arguments_not_columns(self) -> None:
        # REQ-1986: split by whether the remote schema requires the argument.
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [
            _col(
                column_name="region", native_filter_type="graphql_arg", native_filter_required=True
            ),
            _col(
                column_name="status", native_filter_type="graphql_arg", native_filter_required=False
            ),
        ]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert table["columns"] == []
        assert table["required_args"] == [
            {"name": "region", "gql_type": "String", "provisa_type": "text"}
        ]
        assert table["optional_args"] == [
            {"name": "status", "gql_type": "String", "provisa_type": "text"}
        ]

    def test_ordinary_column_carries_type_and_defaults_to_text(self) -> None:
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [_col(column_name="amount", data_type=None)]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert table["columns"] == [{"name": "amount", "type": "text"}]

    def test_gql_selection_is_carried_when_present(self) -> None:
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [_col(column_name="customer", gql_selection="{ id name }")]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert table["columns"][0]["gql_selection"] == "{ id name }"

    def test_object_fields_json_string_is_parsed(self) -> None:
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [_col(column_name="meta", object_fields=json.dumps({"a": 1}))]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert table["columns"][0]["gql_object_fields"] == {"a": 1}

    def test_object_fields_already_a_dict_passes_through(self) -> None:
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [_col(column_name="meta", object_fields={"a": 1})]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert table["columns"][0]["gql_object_fields"] == {"a": 1}

    def test_malformed_object_fields_json_is_dropped_not_raised(self) -> None:
        """A bad object_fields row must not lose the whole table — REQ-1685."""
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [_col(column_name="meta", object_fields="{not json")]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert "gql_object_fields" not in table["columns"][0]

    def test_multiple_columns_preserve_order_and_split_correctly(self) -> None:
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        col_rows = [
            _col(column_name="id"),
            _col(
                column_name="region", native_filter_type="graphql_arg", native_filter_required=True
            ),
            _col(column_name="amount", data_type="numeric"),
        ]
        table = _build_graphql_remote_table(tr, col_rows, "src-1")
        assert [c["name"] for c in table["columns"]] == ["id", "amount"]
        assert [a["name"] for a in table["required_args"]] == ["region"]


class TestObjectTypeSurvivesAReload:
    """#245: what a remote column points at is stored with it, so a table rebuilt from the
    control plane names the same reference columns as at registration."""

    _REGISTERED = {
        "name": "orders",
        "sql_name": "orders",
        "gql_type_name": "Order",
        "columns": [
            {"name": "id", "type": "integer"},
            {
                "name": "customer",
                "type": "jsonb",
                "gql_selection": "customer { id }",
                "gql_object_fields": [{"name": "id", "type": "integer"}],
                "gql_object_type": "Customer",
                "gql_is_list": False,
            },
            {
                "name": "lines",
                "type": "jsonb",
                "gql_selection": "lines { sku }",
                "gql_object_fields": [{"name": "sku", "type": "text"}],
                "gql_object_type": "Line",
                "gql_is_list": True,
            },
        ],
    }

    def _reloaded(self) -> dict:
        from provisa.api.admin._graphql_table_registration import _column_models

        rows = [
            _col(
                column_name=c.name,
                data_type=c.data_type,
                object_fields=[f.model_dump() for f in c.object_fields],
                gql_selection=c.gql_selection,
                gql_object_type=c.gql_object_type,
                gql_is_list=c.gql_is_list,
            )
            for c in _column_models(self._REGISTERED)
        ]
        tr = {"table_name": "orders", "domain_id": "sales", "description": None}
        return _build_graphql_remote_table(tr, rows, "src-1")

    def test_a_reloaded_column_keeps_its_object_type_and_list_flag(self) -> None:
        by_name = {c["name"]: c for c in self._reloaded()["columns"]}
        assert (by_name["customer"]["gql_object_type"], by_name["customer"]["gql_is_list"]) == (
            "Customer",
            False,
        )
        assert (by_name["lines"]["gql_object_type"], by_name["lines"]["gql_is_list"]) == (
            "Line",
            True,
        )
        assert "gql_object_type" not in by_name["id"]

    def test_a_reloaded_table_names_the_same_reference_columns(self) -> None:
        from provisa.graphql_remote.relation_columns import reference_columns

        governed = {"Customer", "Line"}
        assert reference_columns(self._reloaded(), governed) == reference_columns(
            self._REGISTERED, governed
        )
        assert reference_columns(self._reloaded(), governed) == {"customer"}
