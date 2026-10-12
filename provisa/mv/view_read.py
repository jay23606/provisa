# Copyright (c) 2026 Kenneth Stott
# Canary: 5a8d2f61-9c34-4e07-b1f8-3e6a0d9c7b25
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a view reference becomes when a role reads it.

The query compiler's order, on every surface: query -> ONE semantic SQL statement -> governance
-> optimization -> plan -> route -> native.

* Semantic stage (:func:`semantic_statement`): every view the statement reads is replaced by its
  SQL, so governance judges one statement over registered tables, as if the reader had written
  it -- every V-rule (the relationship guard included), row filters, masks, column visibility.
  The view table's own declared rules apply on top.
* Optimization (:func:`unnarrowed_view_bodies`): a view the reader sees whole -- none of its
  inputs carries a rule narrower than "everything" -- is answered from its stored rows when it
  is materialized and fresh. Governance of its SQL changes nothing for that reader, so it stays
  the registered table it is through governance (its own rules applied), and its stored rows are
  put in after.
* A view that names another region (REQ-1921) is read from the copy that region keeps, by every
  reader, with the view's own rules on top: its inputs are not read here. A request-level as-of
  reads a bitemporal view from its append log (REQ-1163).

The pipeline's raw-SQL and compiled stages both call these two, nothing else."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from provisa.compiler.stage2 import GovernanceContext


def _input_names(sql: str) -> set[str]:
    from provisa.events.lineage import extract_inputs  # noqa: PLC0415

    return {name.rsplit(".", 1)[-1] for name in extract_inputs(sql, "postgres")}


def _narrowed(table_id: int, gov: "GovernanceContext") -> bool:
    """Whether the role's rules on ``table_id`` are narrower than "everything"."""
    if table_id in gov.rls_rules:
        return True
    if any(tid == table_id for tid, _ in gov.masking_rules):
        return True
    visible = gov.visible_columns.get(table_id)
    if visible is None:
        return False
    return any(column not in visible for column, _ in gov.all_columns.get(table_id, []))


def sees_everything(
    view: str,
    view_sql_map: dict[str, str],
    gov: "GovernanceContext",
    _seen: frozenset = frozenset(),
) -> bool:
    """Whether the role may read ``view``'s stored rows: none of the tables the view reads —
    directly, or through another view — carries a rule narrower than "everything" for it. An
    input that is neither a registered table nor a view cannot be judged, so it does not qualify."""
    if view in _seen:
        return False
    for name in _input_names(view_sql_map[view]):
        if name in view_sql_map:
            if not sees_everything(name, view_sql_map, gov, _seen | {view}):
                return False
            continue
        table_id = gov.table_map.get(name)
        if table_id is None or _narrowed(table_id, gov):
            return False
    return True


def _stored_rows(view: str, state: Any) -> str | None:
    """A read of ``view``'s stored rows, when it is materialized and its build is fresh."""
    from provisa.mv.models import MVStatus  # noqa: PLC0415

    mv = state.mv_registry.get(f"view-{view}")
    if mv is None or not mv.enabled or mv.status != MVStatus.FRESH or not mv.target_table:
        return None
    return f"SELECT * FROM {mv.stored_ref()}"


def _home_copy(view: str, state: Any) -> str | None:
    """REQ-1921, A VIEW MAY NAME A REGION: a read of the copy another region keeps of ``view`` —
    it names that region, which alone builds it — whoever reads it and whatever they could see in
    its inputs; None for a view this region builds. Whether that copy is built, and its store
    attached, is the statement's residency (``query_residency.read_home_views``)."""
    from provisa.federation.query_residency import home_view_read  # noqa: PLC0415

    mv = state.mv_registry.get(f"view-{view}")
    return None if mv is None else home_view_read(state, mv)


def _with_own_rules(view: str, body: str, gov: "GovernanceContext") -> str:
    """``body`` under the rules declared on the view's own table (its row filter, masks and
    column visibility), when it has any."""
    from provisa.compiler.stage2 import govern_fragment  # noqa: PLC0415
    from provisa.compiler.view_expand import _expand_one  # noqa: PLC0415

    table_id = gov.table_map.get(view)
    if table_id is None or not _narrowed(table_id, gov):
        return body
    own = govern_fragment(f"SELECT * FROM {view}", gov)
    return _expand_one(own, view, body)


def _said_names(row: dict) -> set[str]:
    """Every name a view's SQL could give the registered table ``row``: its table name and alias,
    bare and qualified by its domain or its schema — the one rule a served table and a draft are
    named by (:mod:`provisa.compiler.naming`)."""
    from provisa.compiler.naming import (  # noqa: PLC0415
        apply_sql_name,
        semantic_relation_names,
        stored_relation_names,
    )

    domain, name, alias = row["domain_id"], row["table_name"], row.get("alias")
    said = {name, *stored_relation_names(domain, row["schema_name"], name)}
    for semantic in {apply_sql_name(alias or name), alias}:
        if semantic:
            said.update(semantic_relation_names(domain, semantic))
    return said


def require_inputs_in_service(view_sql: str, state: Any) -> None:
    """REQ-1921: a view's inputs are in service for its readers. A view is answered from the
    tables its SQL names; one of them out of service (a draft) is offered to no reader — through
    a view either. Raises :class:`TableIsDraft` naming it, as a statement naming it directly is
    refused. The view stays as it is: it is answered again once its input is released.

    A name a table in service also answers to is that table's."""
    import sqlglot  # noqa: PLC0415
    from sqlglot import exp  # noqa: PLC0415

    from provisa.compiler.definitions import TableIsDraft  # noqa: PLC0415

    drafts = state.role_build_inputs["draft_tables"]
    if not drafts:
        return
    served: set[str] = set()
    for row in state.tables:
        served |= _said_names(row)
    out_of_service = {
        said: row["table_name"] for row in drafts for said in _said_names(row) - served
    }
    for table in sqlglot.parse_one(view_sql, read="postgres").find_all(exp.Table):
        qualified = f"{table.db}.{table.name}" if table.db else table.name
        if qualified in out_of_service:
            raise TableIsDraft(out_of_service[qualified])


def require_inputs_reached(view_sql: str, gov: "GovernanceContext") -> None:
    """Through a view a reader sees only what it could see in the view's inputs — and a table
    of which it may read nothing, it does not read through a view either. Governing the view's
    body for such a reader removes every column of that table, which leaves a statement the
    engine can only fail. So it is refused here, where the body is chosen, naming the table, in
    the words a statement that names a table outside the role's reach is refused with
    (``pgwire._pipeline``, V000).

    Judged from the reader's own governance context: a table it holds with no visible column,
    and that publishes none to it (REQ-1959). A table the reader sees some columns of is
    governed as ever — the hidden ones removed."""
    import sqlglot  # noqa: PLC0415
    from sqlglot import exp  # noqa: PLC0415

    tree = sqlglot.parse_one(view_sql, read="postgres")
    for table in tree.find_all(exp.Table):
        named = f"{table.db}.{table.name}" if table.db else table.name
        table_id = gov.table_map.get(named, gov.table_map.get(table.name))
        if table_id is None or table_id in gov.public_tables:
            continue
        if gov.visible_columns.get(table_id) == frozenset():
            raise PermissionError(f"[V000] Table {named!r} not accessible for role {gov.role_id!r}")


def _answered_after_governance(
    view: str, view_sql_map: dict[str, str], state: Any, gov: "GovernanceContext", as_of: str | None
) -> bool:
    """Whether ``view`` keeps its reference through governance, its body put in at optimization:
    its region's copy, an as-of read of a bitemporal view, or a materialized view the reader sees
    whole (for that reader, governing its SQL changes nothing)."""
    if _home_copy(view, state) is not None:
        return True
    if as_of and view in (getattr(state, "bitemporal_view_reads", None) or {}):
        return True
    mv = state.mv_registry.get(f"view-{view}")
    return mv is not None and mv.enabled and sees_everything(view, view_sql_map, gov)


def views_read(sql: str, view_sql_map: dict[str, str]) -> dict[str, str]:
    """Every view ``sql`` reads, directly or through another view, with its SQL."""
    read: dict[str, str] = {}
    pending = [sql]
    while pending:
        text = pending.pop()
        for view, view_sql in view_sql_map.items():
            if view not in read and view in text:
                read[view] = view_sql
                pending.append(view_sql)
    return read


def semantic_statement(
    sql: str,
    view_sql_map: dict[str, str],
    state: Any,
    gov: "GovernanceContext",
    *,
    as_of: str | None = None,
) -> tuple[str, str]:
    """``sql`` as ONE semantic statement for governance: ``(governed, validated)``.

    ``governed`` has every view it reads, directly or through another view, replaced by its SQL
    with the view table's own rules on top -- except a view answered after governance, which stays
    the registered table it is. ``validated`` has those expanded too: the V-rules judge every
    table and every join any view reads, for this reader."""
    from provisa.compiler.view_expand import expand_view_refs  # noqa: PLC0415

    bodies: dict[str, str] = {}
    for view, view_sql in views_read(sql, view_sql_map).items():
        require_inputs_in_service(view_sql, state)
        if not _answered_after_governance(view, view_sql_map, state, gov, as_of):
            require_inputs_reached(view_sql, gov)
            bodies[view] = _with_own_rules(view, view_sql, gov)
    governed = expand_view_refs(sql, bodies)
    return governed, expand_view_refs(governed, view_sql_map)


def unnarrowed_view_bodies(
    sql: str, view_sql_map: dict[str, str], state: Any, *, as_of: str | None = None
) -> dict[str, str]:
    """Optimization: what replaces each view ``sql`` still references, directly or through another
    view -- its region's copy, an as-of read of a bitemporal view's append log, its stored rows
    when it is materialized and its build is fresh, else its own SQL. For a governed statement
    these are the views :func:`semantic_statement` kept; for a read that acts for no role (an MV
    refresh builds a view whole) every view."""
    from provisa.mv.bitemporal import as_of_view_map  # noqa: PLC0415

    bitemporal = (getattr(state, "bitemporal_view_reads", None) or {}) if as_of else {}
    as_of_reads = as_of_view_map(view_sql_map, bitemporal, as_of) if as_of else view_sql_map
    bodies: dict[str, str] = {}
    pending = [sql]
    while pending:
        text = pending.pop()
        for view, view_sql in view_sql_map.items():
            if view in bodies or view not in text:
                continue
            if view in bitemporal:
                bodies[view] = as_of_reads[view]
                continue
            stored = _home_copy(view, state) or _stored_rows(view, state)
            if stored is None:
                bodies[view] = view_sql
                pending.append(view_sql)
            else:
                bodies[view] = stored
    return bodies
