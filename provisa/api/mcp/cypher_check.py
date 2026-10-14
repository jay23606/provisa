# Copyright (c) 2026 Kenneth Stott
# Canary: 8b3d6f21-4c97-4e05-a1b8-2f6e9d0c7a53
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What is wrong with a Cypher read Polly would put on the Graph page, before it gets there.

The statement is parsed, translated against the role's own label map and checked as the role, by
the steps the Cypher endpoint runs before it executes anything -- nothing is executed. An invalid
statement never reaches the page: the chat answers the navigate with the real error, and Polly
corrects the statement from it.
"""

# Requirements: REQ-1795, REQ-1848

from __future__ import annotations

from typing import Any


async def cypher_read_problem(state: Any, role_id: str, query: str) -> str | None:
    """Why ``query`` cannot be run on the Graph page as ``role_id``, or None when it can."""
    from provisa.api.rest.cypher_exec import _build_label_map
    from provisa.api.role_surface import role_surface
    from provisa.compiler.sql_rewrite import make_semantic_sql
    from provisa.compiler.sql_validator import validate_sql
    from provisa.compiler.stage2 import build_governance_context
    from provisa.cypher.graph_rewriter import apply_graph_rewrites
    from provisa.cypher.parser import CypherParseError, parse_cypher
    from provisa.cypher.translator import cypher_to_sql
    from provisa.cypher.translator_types import (
        CypherCrossSourceError,
        CypherTranslateError,
        UnregisteredRelationshipType,
    )
    from provisa.pgwire._pipeline import relationship_guard_bypassed
    from provisa.security.rights import effective_domain_access_role

    surface = role_surface(state, role_id)
    if surface is None:
        return f"the schema of role {role_id!r} is not loaded"
    try:
        ast = parse_cypher(query)
    except CypherParseError as exc:
        return str(exc)
    label_map = _build_label_map(surface.context, role_id, state)
    try:
        sql_ast, _params, graph_vars = cypher_to_sql(ast, label_map, {})
        sql_ast = apply_graph_rewrites(sql_ast, graph_vars, label_map)
    except (CypherTranslateError, CypherCrossSourceError, UnregisteredRelationshipType) as exc:
        return str(exc)
    role = effective_domain_access_role(role_id, state.roles)
    violations = validate_sql(
        make_semantic_sql(sql_ast.sql(dialect="postgres"), surface.context),
        surface.context,
        build_governance_context(
            role_id,
            surface.rls,
            state.masking_rules,
            surface.context,
            getattr(state, "tables", []),
            role=role,
            relationships=getattr(state, "relationships", None),
        ),
        role,
        getattr(state, "tables", []),
        bypass_relationship_guard=relationship_guard_bypassed(
            role, state, statement_opts_out=False
        ),
        bypass_uncovered_relationships=True,
    )
    if violations:
        return "; ".join(f"[{v.code}] {v.message}" for v in violations)
    return None


def graph_query(call: dict) -> str | None:
    """The Cypher statement a navigate call puts on the Graph page, if it puts one there."""
    if call["name"] != "navigate":
        return None
    route = str(call["input"].get("route") or "")
    state = call["input"].get("state")
    if not route.startswith("/graph") or not isinstance(state, dict):
        return None
    query = state.get("query")
    return query if isinstance(query, str) and query.strip() else None
