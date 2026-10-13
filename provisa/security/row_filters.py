# Copyright (c) 2026 Kenneth Stott
# Canary: 0c6a4e9b-83d1-4b57-a2fe-6d19c7b05e3a
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Row filters resolved to one predicate per (role, table), once per runtime build.

A row filter attaches to a table, to a domain, or to a tag (REQ-1384). The governance path
reads one predicate per table id, so the three scopes are folded together here, before a
role's RLS context is built, rather than consulted at every request:

- the table's own rule, or failing that the rule on the table's domain (REQ-402), is the base
  predicate — role inheritance has already been folded into these by ``materialize_rls``;
- every rule on a tag the table carries is AND-ed onto it. There are no precedence tiers: a
  tag only ever adds restriction. The acting role's tag rules and those of every ancestor all
  contribute, nearest role first, so a child role cannot shed an ancestor's tag rule.

A rule names a tag by its base id and covers every parameter value the tag is assigned with
("entity" covers "entity:customer").
"""

# Requirements: REQ-1384, REQ-402, REQ-1677

from __future__ import annotations

from collections.abc import Iterable


def tagged_table_ids(tag_assignments: Iterable[dict]) -> dict[str, set[int]]:
    """base tag id → ids of the tables that carry the tag. A tag on a table's column, or on
    its source, is not a tag on the table."""
    out: dict[str, set[int]] = {}
    for a in tag_assignments:
        if a["object_type"] == "table" and a["table_id"] is not None:
            out.setdefault(a["base_tag_id"], set()).add(a["table_id"])
    return out


def _and(predicates: list[str]) -> str:
    if len(predicates) == 1:
        return predicates[0]
    return " AND ".join(f"({p})" for p in predicates)


def resolve_table_rules(
    rls_rules: list[dict],
    tables: Iterable[dict],
    chains: dict[str, list[str]],
    tag_assignments: Iterable[dict],
) -> list[dict]:
    """The rule list with every (role, table) pair's filters folded into one table-level rule.

    ``rls_rules`` is the list ``materialize_rls`` returns. Domain and action rules pass through
    unchanged (an action still resolves its own); table rules are replaced by the folded ones;
    tag rules are consumed.
    """
    table_rules: dict[tuple[str, int], str] = {}
    domain_rules: dict[tuple[str, str], str] = {}
    tag_rules: dict[tuple[str, str], str] = {}
    out: list[dict] = []
    for rule in rls_rules:
        if rule.get("action_name"):
            out.append(rule)
        elif rule.get("tag_id"):
            tag_rules[(rule["role_id"], rule["tag_id"])] = rule["filter_expr"]
        elif rule.get("table_id") is not None:
            table_rules[(rule["role_id"], rule["table_id"])] = rule["filter_expr"]
        elif rule.get("domain_id"):
            domain_rules[(rule["role_id"], rule["domain_id"])] = rule["filter_expr"]
            out.append(rule)

    tags_by_table: dict[int, list[str]] = {}
    for tag_id, table_ids in tagged_table_ids(tag_assignments).items():
        for tid in table_ids:
            tags_by_table.setdefault(tid, []).append(tag_id)

    for rid, chain in chains.items():
        for t in tables:
            tid = t["id"]
            predicates: list[str] = []
            base = table_rules.get((rid, tid))
            if base is None:
                base = domain_rules.get((rid, t.get("domain_id") or ""))
            if base is not None:
                predicates.append(base)
            for tag_id in sorted(tags_by_table.get(tid, ())):
                for anc in chain:
                    tagged = tag_rules.get((anc, tag_id))
                    if tagged is not None:
                        predicates.append(tagged)
            if predicates:
                out.append(
                    {
                        "id": None,
                        "role_id": rid,
                        "table_id": tid,
                        "domain_id": None,
                        "action_name": None,
                        "tag_id": None,
                        "filter_expr": _and(predicates),
                    }
                )
    return out
