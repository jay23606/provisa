# Copyright (c) 2026 Kenneth Stott
# Canary: 3ccd071a-7583-4bfb-8514-154dda094370
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-641: every surface lowers a governed statement to catalog-physical the one way -- its refs
normalized, an unaliased one pinned to its own name, then renamed to the physical table. A Cypher
node read reaches the lowering as a star projection over an unaliased ref; lowered without the
pinning (the compiled path did), its column qualifiers named a table the statement no longer had:
"Referenced table pet_by_status not found" for every Cypher read of an API table."""

from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp

from provisa.compiler.sql_gen import CompilationContext, TableMeta
from provisa.compiler.sql_rewrite import lower_to_catalog_physical

_META = TableMeta(
    table_id=3,
    field_name="pet_by_status",
    type_name="PetByStatus",
    source_id="petstore-api",
    catalog_name="petstore_api",
    schema_name="default",
    table_name="find_pets_by_status",
    domain_id="pet-store",
)

# The shape the Cypher translator hands governance, with its star expanded and qualified.
_CYPHER_NODE = (
    'SELECT n."id", n."name" FROM (SELECT "pet_by_status"."id", "pet_by_status"."name" '
    'FROM "pet_store"."pet_by_status") AS n LIMIT 5'
)


def _ctx() -> CompilationContext:
    ctx = CompilationContext()
    ctx.tables = {"pet_by_status": _META}
    return ctx


def test_an_unaliased_ref_keeps_the_name_its_qualifiers_bind_to():
    lowered = sqlglot.parse_one(lower_to_catalog_physical(_CYPHER_NODE, _ctx()), read="postgres")
    (table,) = lowered.find_all(exp.Table)
    assert (table.catalog, table.db, table.name) == (
        "petstore_api",
        "default",
        "find_pets_by_status",
    )
    assert table.alias == "pet_by_status"
    qualifiers = {c.table for c in lowered.find_all(exp.Column) if c.table and c.table != "n"}
    assert qualifiers == {"pet_by_status"}
