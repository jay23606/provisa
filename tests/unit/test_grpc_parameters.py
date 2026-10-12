# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A gRPC request gives a table's parameters (REQ-1986, REQ-1991).

A table with parameters has a ``{Type}Params`` message beside its ``{Type}Filter``, one
``optional`` field per parameter, and its ``{Type}Request`` a ``params`` field. The native
servicer and the HTTP gRPC proxy (``body["params"]``) lower the parameters into the semantic
SELECT as ``_nf_<name> = $N``, the form an SQL client gives a parameter in, the values bound.
"""

# Requirements: REQ-1986, REQ-1991, REQ-803

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provisa.compiler.introspect import ColumnMetadata
from provisa.compiler.schema_gen import SchemaInput
from provisa.compiler.sql_types import TableMeta
from provisa.grpc.field_numbering import FieldNumberAllocator
from provisa.grpc.proto_gen import generate_proto
from provisa.grpc.query_ir import ParameterError, grpc_table_to_semantic_sql
from provisa.grpc.schema_gen import compile_descriptor_set


def _param(name: str, *, required: bool) -> dict:
    return {
        "column_name": f"_nf_{name}",
        "visible_to": [],
        "native_filter_type": "query_param",
        "native_filter_required": required,
    }


def _si() -> SchemaInput:
    def _table(table_id: int, name: str, columns: list[dict]) -> dict:
        return {
            "id": table_id,
            "source_id": "api",
            "domain_id": "sales",
            "schema_name": "public",
            "table_name": name,
            "columns": [{"column_name": "id", "visible_to": ["admin"]}, *columns],
            "write_ops": [],
            "write_returns_rows": False,
            "write_refused_forms": [],
        }

    return SchemaInput(
        tables=[
            _table(1, "orders", [_param("region", required=True), _param("min", required=False)]),
            _table(2, "customers", []),
        ],
        relationships=[],
        column_types={
            1: [
                ColumnMetadata(column_name="id", data_type="integer", is_nullable=False),
                ColumnMetadata(column_name="_nf_region", data_type="varchar", is_nullable=True),
                ColumnMetadata(column_name="_nf_min", data_type="double", is_nullable=True),
            ],
            2: [ColumnMetadata(column_name="id", data_type="integer", is_nullable=False)],
        },
        naming_rules=[],
        role={"id": "admin", "domain_access": ["*"], "capabilities": []},
        domains=[{"id": "sales", "description": "Sales"}],
    )


def _message_block(proto: str, name: str) -> str:
    start = proto.index(f"message {name} {{")
    return proto[start : proto.index("}", start) + 1]


def test_a_table_with_parameters_has_a_params_message_and_request_field():
    proto = generate_proto(_si())
    params = _message_block(proto, "OrdersParams")
    assert "optional double min = 1;" in params
    assert "optional string region = 2;" in params
    assert "OrdersParams params = 6;" in _message_block(proto, "OrdersRequest")
    # A parameter is not a filter field.
    assert "region" not in _message_block(proto, "OrdersFilter")
    # The proto compiles.
    assert compile_descriptor_set(proto)


def test_a_table_without_parameters_has_neither():
    proto = generate_proto(_si())
    assert "message CustomersParams" not in proto
    assert "params" not in _message_block(proto, "CustomersRequest")


def test_parameter_field_numbers_are_kept_under_their_own_kind():
    """REQ-1903: a parameter keeps its number when another is added before it."""
    allocator = FieldNumberAllocator([("1", "params", "region", 7, False)])
    proto = generate_proto(_si(), field_numbers=allocator)
    params = _message_block(proto, "OrdersParams")
    assert "optional string region = 7;" in params
    assert "optional double min = 8;" in params


def _ctx():
    meta = TableMeta(
        table_id=1,
        field_name="orders",
        type_name="Orders",
        source_id="api",
        catalog_name="api",
        schema_name="public",
        table_name="orders",
    )
    return SimpleNamespace(
        tables={"orders": meta},
        aggregate_columns={1: [("id", "integer"), ("region", "varchar")]},
        native_filter_columns={1: {"_nf_region": "varchar", "_nf_min": "double"}},
    )


def _params_message(**set_fields):
    fields = [SimpleNamespace(name=name) for name in ("region", "min")]
    return SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(fields=fields),
        HasField=lambda name: name in set_fields,
        **set_fields,
    )


@pytest.mark.parametrize(
    "params",
    [_params_message(region="EU", min=10.5), {"region": "EU", "min": 10.5}],
    ids=["native", "proxy"],
)
def test_parameters_lower_to_bound_predicates_after_the_filter(params):
    sql, bound = grpc_table_to_semantic_sql(  # type: ignore[misc]
        _ctx(), "Orders", 5, {"region": "x"}, None, params
    )
    assert 'WHERE "region" = $1 AND "_nf_region" = $2 AND "_nf_min" = $3 LIMIT $4' in sql
    assert bound == ["x", "EU", 10.5, 5]


def test_a_name_that_is_not_a_parameter_is_refused_naming_it():
    with pytest.raises(ParameterError, match="'colour'") as err:
        grpc_table_to_semantic_sql(_ctx(), "Orders", 0, None, None, {"colour": "red"})
    assert err.value.field == "colour"


def test_a_proxy_value_of_another_type_is_refused():
    with pytest.raises(ParameterError, match="must be a number"):
        grpc_table_to_semantic_sql(_ctx(), "Orders", 0, None, None, {"min": "lots"})


@pytest.mark.asyncio
async def test_the_servicer_hands_the_pipeline_the_parameters(monkeypatch):
    from tests.unit import test_grpc_read_mask as harness

    plain_ctx = harness._ctx

    def _ctx_with_parameters():
        ctx = plain_ctx()
        ctx.native_filter_columns = {1: {"_nf_region": "varchar"}}
        return ctx

    monkeypatch.setattr(harness, "_ctx", _ctx_with_parameters)
    servicer, _msg_cls = harness._servicer()
    params = SimpleNamespace(
        DESCRIPTOR=SimpleNamespace(fields=[SimpleNamespace(name="region")]),
        HasField=lambda name: name == "region",
        region="EU",
    )
    request = SimpleNamespace(
        limit=0,
        read_mask=SimpleNamespace(paths=[]),
        params=params,
        HasField=lambda name: name == "params",
        DESCRIPTOR=SimpleNamespace(fields_by_name={"params": object()}),
    )
    result = SimpleNamespace(column_names=["order_id"], rows=[])
    govern = await harness._run(servicer, request, harness._context(), result)

    govern.assert_awaited_once()
    assert '"_nf_region" = $1' in govern.await_args.args[0]
    assert govern.await_args.kwargs["exec_params"] == ["EU"]
