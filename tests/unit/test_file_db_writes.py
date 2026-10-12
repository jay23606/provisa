# Copyright (c) 2026 Kenneth Stott
# Canary: d9a78763-c288-4bf2-887a-e5ca7bd68205
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1997, the maintainer's ruling: "writes back to file databases in a multi-node env - just
error them out when they can't a lock on it." A DuckDB file is held read-only by everything in
a process; a write pauses those holders, opens it read-write for the statement and closes it,
and is refused, naming its source, when another process has the file open. A SQLite write does
not wait for another's lock. On an encrypted org folder whose mount is shared, where no lock
reaches the other nodes, a write is refused outright."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb
import pytest

import provisa.core.settings_catalog  # noqa: F401 -- declares the settings read here
from provisa.core import settings_registry
from provisa.executor.drivers.duckdb_driver import DuckDBDriver
from provisa.executor.drivers.sqlalchemy_driver import SQLAlchemyDriver
from provisa.executor.pool import SourcePool
from provisa.federation import file_locks


@contextmanager
def _held_elsewhere(code: str) -> Iterator[None]:
    other = subprocess.Popen(
        [sys.executable, "-c", code + "\nprint('held', flush=True)\nimport time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert other.stdout is not None
        assert other.stdout.readline().strip() == "held"
        yield
    finally:
        other.kill()
        other.wait()


@pytest.fixture
def duck(tmp_path):
    path = str(tmp_path / "shop.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE orders (id INTEGER); INSERT INTO orders VALUES (1)")
    con.close()
    return path


def _pool_with(source_id: str, driver) -> SourcePool:
    pool = SourcePool.__new__(SourcePool)
    pool._drivers = {source_id: driver}  # type: ignore[attr-defined]
    return pool


@pytest.fixture
def not_shared(monkeypatch):
    """The org file mount is this node's own (``org_files.shared_mount`` off)."""
    real = settings_registry.value
    monkeypatch.setattr(
        settings_registry,
        "value",
        lambda key: False if key == "org_files.shared_mount" else real(key),
    )


async def test_on_one_node_a_write_to_a_duckdb_file_goes_through_and_reads_see_it(duck, not_shared):
    driver = DuckDBDriver()
    await driver.connect("", 0, duck, "", "")
    # The engine's attach of the same file, held read-only and let go while the write runs.
    engine = duckdb.connect()
    engine.execute(f"ATTACH '{duck}' AS shop (READ_ONLY)")

    @contextmanager
    def engine_paused():
        engine.execute("DETACH shop")
        try:
            yield
        finally:
            engine.execute(f"ATTACH '{duck}' AS shop (READ_ONLY)")

    token = file_locks.register(duck, engine_paused)
    try:
        await driver.execute("INSERT INTO orders VALUES (2)")
        assert (await driver.execute("SELECT count(*) FROM orders")).rows == [(2,)]
        assert engine.execute("SELECT count(*) FROM shop.orders").fetchone() == (2,)
        with pytest.raises(duckdb.Error, match="read-only"):
            engine.execute("INSERT INTO shop.orders VALUES (3)")
    finally:
        file_locks.unregister(duck, token)
        engine.close()
        await driver.close()


async def test_a_duckdb_write_while_another_process_has_the_file_is_refused_naming_the_source(
    duck, not_shared
):
    driver = DuckDBDriver()
    await driver.connect("", 0, duck, "", "")
    pool = _pool_with("shop", driver)
    try:
        holder = f"import duckdb\nc = duckdb.connect({duck!r}, read_only=True)"
        with _held_elsewhere(holder):
            # Reads share the file with the other process.
            assert (await pool.execute("shop", "SELECT count(*) FROM orders")).rows == [(1,)]
            with pytest.raises(file_locks.FileLocked) as refused:
                await pool.execute("shop", "INSERT INTO orders VALUES (2)")
        assert refused.value.source_id == "shop"
        assert "source 'shop'" in str(refused.value) and "is locked" in str(refused.value)
        # The refused write left the driver reading, and the file unchanged.
        assert (await pool.execute("shop", "SELECT count(*) FROM orders")).rows == [(1,)]
        await pool.execute("shop", "INSERT INTO orders VALUES (2)")  # the holder gone, it goes
    finally:
        await driver.close()


async def test_a_sqlite_write_while_another_process_writes_is_refused_naming_the_source(
    tmp_path, not_shared
):
    path = str(tmp_path / "survey.sqlite")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE answers (a INTEGER)")
    con.commit()
    con.close()
    driver = SQLAlchemyDriver("sqlite")
    await driver.connect("", 0, path, "", "")
    pool = _pool_with("survey", driver)
    try:
        holder = (
            f"import sqlite3\nc = sqlite3.connect({path!r})\n"
            "c.execute('BEGIN IMMEDIATE')\nc.execute('INSERT INTO answers VALUES (1)')"
        )
        with _held_elsewhere(holder):
            with pytest.raises(file_locks.FileLocked) as refused:
                await pool.execute("survey", "INSERT INTO answers VALUES (2)")
        assert refused.value.source_id == "survey"
        await pool.execute("survey", "INSERT INTO answers VALUES (2)")
        assert (await pool.execute("survey", "SELECT a FROM answers")).rows == [(2,)]
    finally:
        await driver.close()


async def test_on_an_encrypted_shared_org_folder_a_write_is_refused_outright(tmp_path, monkeypatch):
    from provisa.core import org_files, org_folder_crypt

    monkeypatch.setenv("PROVISA_DATA_DIR", str(tmp_path / "data"))
    real = settings_registry.value
    monkeypatch.setattr(
        settings_registry,
        "value",
        lambda key: True if key == "org_files.shared_mount" else real(key),
    )
    folder = org_files.folder("acme")
    (folder / "files" / "shop").mkdir(parents=True)
    path = str(folder / "files" / "shop" / "shop.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE orders (id INTEGER)")
    con.close()
    driver = DuckDBDriver()
    await driver.connect("", 0, path, "", "")
    pool = _pool_with("shop", driver)
    try:
        # Not encrypted: the shared mount's own lock protects the write.
        await pool.execute("shop", "INSERT INTO orders VALUES (1)")
        monkeypatch.setattr(org_folder_crypt, "is_encrypted", lambda f: f == folder)
        with pytest.raises(file_locks.UnprotectedWrite) as refused:
            await pool.execute("shop", "INSERT INTO orders VALUES (2)")
        assert "source 'shop'" in str(refused.value) and "encrypted" in str(refused.value)
        # Reads go on.
        assert (await pool.execute("shop", "SELECT count(*) FROM orders")).rows == [(1,)]
    finally:
        await driver.close()
