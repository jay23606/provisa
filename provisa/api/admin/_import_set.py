# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The save-time refusal of a table's import set (REQ-1954): only a ServiceNow table is bound to
one, and only to the import set of one of the instance's active transform maps that write into
it."""

# Requirements: REQ-1954

from __future__ import annotations

from typing import Any

from provisa.api.admin.types import MutationResult


async def table_import_set_refusal(conn: Any, model: Any) -> MutationResult | None:
    """A failing MutationResult when ``model`` names an import set and its source is not a
    ServiceNow source, or the import set is not one of the instance's active transform maps into
    the table; None otherwise."""
    import_set = model.import_set
    if not import_set:
        return None
    from provisa.core.repositories import source as source_repo
    from provisa.core.repositories.source import source_from_row
    from provisa.core.secrets_store import bound_to_request_org
    from provisa.federation.pgwire_replica import servicenow_transform_maps

    row = await source_repo.get(conn, model.source_id)
    if row is None or row["type"] != "servicenow":
        return MutationResult(
            success=False,
            message=f"table {model.table_name!r}: an import set is defined only for a ServiceNow "
            f"source, not {(row or {}).get('type')!r}",
            code="schema.import_set_not_servicenow",
            params={"table": model.table_name, "source": model.source_id},
        )
    async with bound_to_request_org():
        maps = await servicenow_transform_maps(
            source_from_row(row), model.schema_name, model.table_name
        )
    if import_set not in {staging for _name, staging in maps}:
        return MutationResult(
            success=False,
            message=f"table {model.table_name!r}: {import_set!r} is not the import set of an "
            "active transform map into it",
            code="schema.import_set_unknown",
            params={"table": model.table_name, "importSet": import_set},
        )
    return None
