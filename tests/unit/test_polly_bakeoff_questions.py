# Copyright (c) 2026 Kenneth Stott
# Canary: 3e8b0d52-71c4-4f96-a2d8-5c9f1e6b4a07
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Every Polly bake-off grading query names its own demo's tables and views as they register
(REQ-2012): ``"<domain>"."<alias or table>"``, a view as ``view_<id>``, and only columns those
relations have. Checked against that demo's own config, with no server: a query naming a relation
the demo does not register is refused on the demo (V006), and the run then fails before it asks
any model."""

# Requirements: REQ-2012

from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot
import yaml
from sqlglot import exp

from provisa.core.config_loader import views_as_tables
from tests.integration.polly_bakeoff_questions import QUESTIONS

_NAMED = Path(__file__).resolve().parents[2] / "demo" / "named"
_ASKED = [(demo, q) for demo, questions in QUESTIONS.items() for q in questions]


def _relations(demo: str) -> dict[tuple[str, str], set[str]]:
    """(domain, name) -> columns, for every table and view ``demo`` registers."""
    config = views_as_tables(yaml.safe_load((_NAMED / demo / "config.yaml").read_text()))
    return {
        (t["domain_id"], t.get("alias") or t["table"]): {c["name"] for c in t["columns"]}
        for t in config["tables"]
    }


@pytest.mark.parametrize(
    ("demo", "question"), _ASKED, ids=[f"{demo}: {q.text}" for demo, q in _ASKED]
)
def test_each_grading_query_names_registered_relations_and_their_columns(demo, question):
    relations = _relations(demo)
    tree = sqlglot.parse_one(question.answer_sql, read="postgres")
    read: set[str] = set()
    for table in tree.find_all(exp.Table):
        key = (table.db, table.name)
        assert key in relations, f"{question.text}: {table.sql()} is not a registered relation"
        read |= relations[key]
    # What the query computes and names itself: its output aliases and derived-table columns.
    named = {a.alias for a in tree.find_all(exp.Alias)}
    for column in tree.find_all(exp.Column):
        assert column.name in read | named, (
            f"{question.text}: column {column.name!r} is in none of the relations it reads"
        )


@pytest.mark.parametrize("demo", sorted(QUESTIONS))
def test_each_set_of_questions_names_a_named_demo(demo):
    assert (_NAMED / demo / "config.yaml").is_file(), f"no named demo {demo!r} to ask them on"
