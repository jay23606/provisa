# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A write on the engine route is lowered to the engine's write grammar (REQ-910).

The pipeline names a write's target by an alias equal to the table name. PostgreSQL takes that
on the DIRECT route; Trino's INSERT has no target alias, so on the engine route the self-alias is
dropped — keeping the INSERT's column list, which PostgreSQL's ``t AS t (a, b)`` parses onto it.
"""

# Requirements: REQ-910, REQ-031

from __future__ import annotations

import pytest
import sqlglot

from provisa.compiler.sql_rewrite import unalias_write_target


@pytest.mark.parametrize(
    "sql, lowered",
    [
        (
            'INSERT INTO "c"."s"."g" AS "g" (id, name) VALUES (2, \'B\')',
            'INSERT INTO "c"."s"."g" (id, name) VALUES (2, \'B\')',
        ),
        (
            'INSERT INTO "c"."s"."g" AS "g" VALUES (2, \'B\')',
            'INSERT INTO "c"."s"."g" VALUES (2, \'B\')',
        ),
        (
            'DELETE FROM "c"."s"."g" AS "g" WHERE "g"."id" = 1',
            'DELETE FROM "c"."s"."g" WHERE "g"."id" = 1',
        ),
    ],
)
def test_a_write_loses_its_self_alias_and_keeps_its_columns(sql, lowered):
    assert unalias_write_target(sql) == lowered
    # What the engine is then sent parses in Trino's grammar.
    sqlglot.parse_one(sqlglot.transpile(lowered, read="postgres", write="trino")[0], read="trino")


def test_a_read_and_a_real_alias_are_left_alone():
    read = 'SELECT "g".id FROM "c"."s"."g" AS "g"'
    assert unalias_write_target(read) == read
    named = 'INSERT INTO "c"."s"."g" AS "x" (id) VALUES (1)'
    assert unalias_write_target(named) == named


def test_an_engine_write_runs_without_query_retries():
    # A write the engine makes through a source's connector is not replayed: under fault-tolerant
    # execution a connector without retry support refuses it ("does not support query retries").
    from types import SimpleNamespace

    from provisa.pgwire._pipeline import _engine_session_hints

    state = SimpleNamespace(
        source_types={"cass": "cassandra", "events": "kafka", "pg": "postgresql"},
        source_federation_hints={},
    )

    def hints(sources: set[str], *, writes: bool):
        return _engine_session_hints(state, sources, None, "SELECT 1", writes=writes)

    assert hints({"cass"}, writes=True) == {"retry_policy": "NONE"}
    assert hints({"events"}, writes=False) == {"retry_policy": "NONE"}
    assert hints({"pg"}, writes=False) is None
