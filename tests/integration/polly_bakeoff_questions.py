# Copyright (c) 2026 Kenneth Stott
# Canary: 6a1f3c84-9d27-4b50-8e16-2c7b9a4d0f53
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The Polly bake-off's questions, each with the SQL whose rows are its right answers (REQ-2012).

Each named demo has its own questions (QUESTIONS, by demo name), asked on that demo and graded
over its tables: the weblogs demo's by tests/integration/test_polly_bakeoff_e2e.py. A demo's tour
may ask Polly any of its own (tests/unit/test_named_demo_tour.py), and every grading query names
its demo's tables and views as they register (tests/unit/test_polly_bakeoff_questions.py)."""

# Requirements: REQ-2012

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    text: str
    # The SQL whose rows are the right answers: a reply is right when it names any of them (a tie
    # for "the most" makes each tied value right).
    answer_sql: str


# The weblogs demo's own question, the one its tour answers in SQL and over REST.
DEMO_QUESTION = "Which pages are slowest, and which SQL makes them slow?"

WEBLOGS = (
    Question(
        "How many customers does the shop have?", 'SELECT COUNT(*) AS a FROM "shop"."customers"'
    ),
    Question("How many orders have been placed?", 'SELECT COUNT(*) AS a FROM "shop"."orders"'),
    Question(
        "How many requests are in the web access log?",
        'SELECT COUNT(*) AS a FROM "shop"."access_log"',
    ),
    Question(
        "How many requests were answered with a server error (a 5xx status)?",
        'SELECT COUNT(*) AS a FROM "shop"."access_log" WHERE status >= 500',
    ),
    Question(
        "Which product category has the most products?",
        'SELECT category AS a FROM "shop"."products" GROUP BY category '
        'HAVING COUNT(*) = (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM "shop"."products" '
        "GROUP BY category) AS c)",
    ),
    Question(
        "What is the name of the most expensive product?",
        'SELECT name AS a FROM "shop"."products" '
        'WHERE price = (SELECT MAX(price) FROM "shop"."products")',
    ),
    Question(
        "Which city has the most customers?",
        'SELECT city AS a FROM "shop"."customers" GROUP BY city '
        'HAVING COUNT(*) = (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM "shop"."customers" '
        "GROUP BY city) AS c)",
    ),
    Question(
        "Which page path was requested most often?",
        'SELECT path AS a FROM "shop"."access_log" GROUP BY path '
        'HAVING COUNT(*) = (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM "shop"."access_log" '
        "GROUP BY path) AS c)",
    ),
    Question(
        "How many distinct customers have placed at least one order?",
        'SELECT COUNT(DISTINCT customer_id) AS a FROM "shop"."orders"',
    ),
    Question(
        "Which database table did the shop's SQL statements touch most often?",
        'SELECT table_name AS a FROM "shop"."view_slow_statements_by_table" WHERE statements = '
        '(SELECT MAX(statements) FROM "shop"."view_slow_statements_by_table")',
    ),
    # The demo's own question: right when the reply names the slowest page, on average.
    Question(
        DEMO_QUESTION,
        'SELECT path AS a FROM "shop"."view_slowest_pages" GROUP BY path '
        "ORDER BY AVG(page_ms) DESC LIMIT 1",
    ),
)

# Each named demo's questions, by its name (its directory under demo/named).
QUESTIONS: dict[str, tuple[Question, ...]] = {"weblogs": WEBLOGS}
