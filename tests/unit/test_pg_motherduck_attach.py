# Copyright (c) 2026 Kenneth Stott
# Canary: a9e821b0-0a56-48b5-b352-1579b9e2d93f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""Issue 254, REQ-1868: a MotherDuck table on the Postgres engine is the table pg_duckdb's sync
worker creates, in the schema its own naming gives, once the sync has run -- not an imported
foreign schema. The live proof is tests/integration/test_pg_duckdb_motherduck_live.py."""

from __future__ import annotations

import pytest

from provisa.federation import pg_motherduck as md


@pytest.mark.parametrize(
    ("database", "schema", "expected"),
    [
        ("my_db", "main", "public"),
        ("My_DB", "main", "public"),  # MotherDuck names are case-insensitive
        ("my_db", "sales", "sales"),
        ("sample_data", "main", "ddb$sample_data"),
        ("sample_data", "nyc", "ddb$sample_data$nyc"),
    ],
)
def test_the_schema_is_pg_duckdbs_naming(database, schema, expected):
    assert md.synced_schema(database, schema, "my_db") == expected


class _Cursor:
    """A Postgres engine connection: what it holds, and what is run on it."""

    def __init__(self, *, server=None, mapping=None, synced_after=0, schema="ddb$sample_data$nyc"):
        self.server, self.mapping = server, mapping
        self.statements: list[tuple[str, tuple]] = []
        self._polls_left, self._schema = synced_after, schema
        self._row = None

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))
        if "FROM pg_foreign_server" in sql:
            self._row = None if self.server is None else (self.server,)
        elif sql.startswith("CREATE SERVER"):
            self.server = "motherduck"
        elif "FROM pg_user_mappings" in sql:
            self._row = None if self.mapping is None else (self.mapping,)
        elif sql.startswith("CREATE USER MAPPING"):
            self.mapping = [f"token={params[0]}"]
        elif "current_database()" in sql:
            self._row = ("My_db",)
        elif "FROM pg_class" in sql:
            if self._polls_left:
                self._polls_left -= 1
                self._row = None
            else:
                self._row = (self._schema,)

    def fetchone(self):
        return self._row


_DETAILS = {"database": "sample_data", "token": "s3cr3t-value", "server_options": {}}


def test_the_engine_is_signed_in_and_the_synced_table_is_read(monkeypatch):
    monkeypatch.setattr(md, "_POLL_S", 0)
    cur = _Cursor(synced_after=3)
    assert md.attach(cur, _DETAILS, "md", "nyc", "taxi", 5) == '"ddb$sample_data$nyc"."taxi"'
    created = [s for s, _ in cur.statements if s.startswith("CREATE")]
    assert (
        created[0] == "CREATE SERVER \"motherduck\" TYPE 'motherduck' FOREIGN DATA WRAPPER duckdb"
    )
    assert created[1].startswith('CREATE USER MAPPING FOR CURRENT_USER SERVER "motherduck"')
    # the token is a bound value, never part of the statement text
    assert all("s3cr3t-value" not in s for s, _ in cur.statements)


def test_the_engines_server_is_used_whatever_it_is_named():
    cur = _Cursor(server="their_md", mapping=["token=s3cr3t-value"])
    md.attach(cur, _DETAILS, "md", "nyc", "taxi", 5)
    assert not [s for s, _ in cur.statements if s.startswith("CREATE")]
    assert ("their_md",) in [p for s, p in cur.statements if "pg_user_mappings" in s]


def test_another_motherduck_account_is_refused_by_name():
    cur = _Cursor(server="motherduck", mapping=["token=someone-else"])
    with pytest.raises(md.MotherDuckAttachError, match="signed in to another MotherDuck account"):
        md.attach(cur, _DETAILS, "md", "nyc", "taxi", 5)


def test_a_table_the_sync_never_creates_is_refused_naming_where_it_was_looked_for(monkeypatch):
    monkeypatch.setattr(md, "_POLL_S", 0)
    cur = _Cursor(synced_after=10**9)
    with pytest.raises(
        md.MotherDuckAttachError,
        match=r"sample_data\.nyc\.taxi did not appear in Postgres schema 'ddb\$sample_data\$nyc'",
    ):
        md.attach(cur, _DETAILS, "md", "nyc", "taxi", 0)


def test_server_options_are_bound_values():
    cur = _Cursor()
    md.attach(
        cur, {**_DETAILS, "server_options": {"default_database": "x"}}, "md", "nyc", "taxi", 5
    )
    server = next((s, p) for s, p in cur.statements if s.startswith("CREATE SERVER"))
    assert server == (
        "CREATE SERVER \"motherduck\" TYPE 'motherduck' FOREIGN DATA WRAPPER duckdb "
        "OPTIONS (default_database %s)",
        ("x",),
    )
