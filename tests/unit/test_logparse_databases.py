# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the database and runtime log presets read the lines each project's documentation
gives (tests/unit/fixtures/logparse/databases), one fixture per preset; a record over several
lines (a statement, a stack trace, a slow query) is read whole."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog, records

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "databases"
_UTC = timezone.utc
_LOCAL = timezone(timedelta(hours=-4))


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_LOCAL))


def rows(name: str, *, keep_refused: bool = False) -> list:
    fmt = BUILT_IN[name]
    ctx = _ctx()
    body = list(enumerate((_FIXTURES / f"{name}.log").read_text().splitlines()))
    out: list = []
    for _, record in records(body, fmt.record_start):
        try:
            out.extend(fmt.parse_many(record, ctx))
        except ParseError as exc:
            if not keep_refused:
                raise
            out.append(str(exc))
    return out


def test_the_database_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in (
        "postgresql_stderr",
        "postgresql_csvlog",
        "postgresql_jsonlog",
        "mysql_error",
        "mysql_slow",
        "mongodb",
        "redis",
        "log4j2_default",
        "logback_default",
        "python_logging",
    ):
        assert names[name] == "databases"


def test_postgresql_stderr_joins_a_statement_s_lines():
    ready, error, statement = rows("postgresql_stderr")
    assert ready["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456000, tzinfo=_UTC)
    assert (ready["pid"], ready["severity"]) == ("1234", "LOG")
    assert error["message"] == 'relation "orderz" does not exist at character 15'
    assert statement["severity"] == "STATEMENT"
    assert statement["message"] == "SELECT *\n\t  FROM orderz;"


def test_postgresql_csvlog_with_a_quoted_newline():
    error, ready = rows("postgresql_csvlog")
    assert error["log_time"] == datetime(2023, 5, 11, 8, 16, 1, 2000, tzinfo=_UTC)
    assert (error["user_name"], error["database_name"], error["process_id"]) == (
        "app",
        "shop",
        "2345",
    )
    assert (error["error_severity"], error["sql_state_code"]) == ("ERROR", "42P01")
    assert error["message"] == 'relation "orderz" does not exist'
    assert error["query"] == "SELECT *\n  FROM orderz;"
    assert (error["backend_type"], error["query_id"]) == ("client backend", "0")
    assert ready["user_name"] is None and ready["backend_type"] == "postmaster"


def test_postgresql_jsonlog():
    (row,) = rows("postgresql_jsonlog")
    assert row["timestamp"] == datetime(2023, 5, 11, 8, 16, 1, 2000, tzinfo=_UTC)
    assert row["session_start"] == datetime(2023, 5, 11, 8, 15, 59, tzinfo=_UTC)
    assert (row["error_severity"], row["state_code"], row["pid"]) == ("ERROR", "42P01", 2345)
    assert row["remote_port"] == 51234  # a field without a column is kept for extra


def test_a_postgresql_time_in_another_zone_is_read_in_the_file_s():
    row = BUILT_IN["postgresql_stderr"].parse("2023-05-11 04:15:23.456 EDT [1] LOG:  x", _ctx())
    assert row["timestamp"] == datetime(2023, 5, 11, 4, 15, 23, 456000, tzinfo=_LOCAL)
    row = BUILT_IN["postgresql_stderr"].parse("2023-05-11 10:15:23 +02 [1] LOG:  x", _ctx())
    assert row["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, tzinfo=_UTC)


def test_mysql_error_log():
    ready, warning = rows("mysql_error")
    assert ready["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (ready["thread"], ready["priority"], ready["error_code"], ready["subsystem"]) == (
        "0",
        "System",
        "MY-010931",
        "Server",
    )
    assert warning["priority"] == "Warning" and "could not be resolved" in warning["message"]


def test_mysql_slow_query_log_is_an_entry_a_query():
    found = rows("mysql_slow", keep_refused=True)
    assert isinstance(found[0], str)  # the server's banner before the first entry
    first, second = found[1:]
    assert first["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456789, tzinfo=_UTC)
    assert (first["user"], first["host"], first["ip"], first["connection_id"]) == (
        "app",
        "localhost",
        None,
        "12",
    )
    assert (first["query_time_s"], first["rows_examined"], first["database"]) == (
        "2.500000",
        "100000",
        "shop",
    )
    assert first["query"] == "SELECT * FROM orders\n  WHERE customer = 'acme';"
    assert (second["host"], second["ip"], second["database"]) == ("app-host", "10.0.0.9", None)


def test_mongodb_structured_log():
    accepted, slow = rows("mongodb")
    assert accepted["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456000, tzinfo=_UTC)
    assert (accepted["severity"], accepted["component"], accepted["id"]) == ("I", "NETWORK", 22943)
    assert accepted["attributes"]["connectionId"] == 12
    assert (slow["severity"], slow["message"]) == ("W", "Slow query")


def test_redis_log():
    starting, ready = rows("redis")
    assert starting["timestamp"] == datetime(2023, 5, 11, 8, 15, 23, 456000, tzinfo=_LOCAL)
    assert (starting["role"], starting["level"]) == ("child", "warning")
    assert (ready["role"], ready["level"], ready["message"]) == (
        "master",
        "notice",
        "Ready to accept connections tcp",
    )


@pytest.mark.parametrize("name", ["log4j2_default", "logback_default"])
def test_java_default_pattern_joins_a_stack_trace(name):
    started, failed = rows(name)
    # The default pattern writes the time of day: the day is the file's last write's.
    assert started["timestamp"] == datetime(2026, 10, 12, 8, 15, 23, 456000, tzinfo=_LOCAL)
    assert (started["thread"], started["level"], started["logger"]) == (
        "main",
        "INFO",
        "com.example.App",
    )
    assert failed["level"] == "ERROR"
    assert failed["message"].splitlines()[0] == "Failed to load order 7"
    assert "OrderService.java:42" in failed["message"]


def test_python_logging_default_joins_a_traceback():
    warning, error = rows("python_logging")
    assert (warning["level"], warning["logger"], warning["message"]) == (
        "WARNING",
        "root",
        "Watch out!",
    )
    assert error["logger"] == "app.orders"
    assert error["message"].splitlines()[-1] == "KeyError: 7"
