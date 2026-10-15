# Copyright (c) 2026 Kenneth Stott
# Canary: 22212ef7-ecc7-4ad8-a069-abdd0193e9d0
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An embedded Postgres for tests: the pgserver wheel's PostgreSQL, on a plain TCP address.

pgserver is a product dependency (the desktop profile and the embedded engine run on it). This
module runs its server the way a test reaches a real one: on ``127.0.0.1`` and a leased port, with
the ``provisa`` role and database the docker stack has. pgserver's own ``get_server`` listens on a
Unix socket only; this starts the same binaries with ``pg_ctl`` and a TCP listener instead. The
binaries are only run, never written to. The data is throwaway, so durability is off (fsync,
synchronous_commit, full_page_writes).

A test that needs Postgres gets its own server here rather than whatever listens on the machine's
5432, which other jobs start and stop.

A server does not outlive the process that started it. A session ended by a signal (a stopped job,
a runner's timeout) runs no teardown, and its server kept running, holding the machine's shared
memory until no further one could start. Each server's directory records its starter's pid
(``owner.pid``), and every start first stops the servers whose starter is gone; a running
session's is left alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROLE = "provisa"
PASSWORD = "provisa"
DATABASE = "provisa"

_PREFIX = "pv-pg-"
_OWNER = "owner.pid"

_SETTINGS = {
    "fsync": "off",
    "synchronous_commit": "off",
    "full_page_writes": "off",
    "max_connections": "300",
    # The zone a session reads a timestamptz back in: UTC, as the postgres image the docker stack and
    # CI run is. pgserver's initdb takes the machine's, so a test on a laptop read 04:00-04:00 for
    # 08:00+00:00 where CI reads the latter.
    "timezone": "UTC",
}


def _bin(name: str) -> str:
    from pgserver.postgres_server import POSTGRES_BIN_PATH

    return str(POSTGRES_BIN_PATH / name)


@dataclass
class LocalPostgres:
    """A running embedded Postgres on ``127.0.0.1:port`` (see the module docstring)."""

    port: int
    root: Path
    # Server settings over the defaults this session's clusters run with (e.g. wal_level).
    settings: dict[str, str] = field(default_factory=dict)

    @property
    def data(self) -> Path:
        return self.root / "data"

    def url(self, database: str = DATABASE, *, driver: str = "psycopg") -> str:
        return f"postgresql+{driver}://{ROLE}:{PASSWORD}@127.0.0.1:{self.port}/{database}"

    def dsn(self, database: str = DATABASE) -> str:
        """A libpq DSN (asyncpg, psycopg, postgres_fdw) for ``database`` as the ``provisa`` role."""
        return f"postgresql://{ROLE}:{PASSWORD}@127.0.0.1:{self.port}/{database}"

    def restart(self, *, preload: tuple[str, ...]) -> None:
        """Restart with ``shared_preload_libraries`` set to ``preload`` (pg_duckdb loads only so)."""
        self._ctl("stop", "-m", "fast")
        self._start(preload)

    def stop(self) -> None:
        self._ctl("stop", "-m", "fast")
        shutil.rmtree(self.root)

    def _ctl(self, *args: str) -> None:
        subprocess.run(
            [_bin("pg_ctl"), "-D", str(self.data), "-w", *args], check=True, capture_output=True
        )

    def _start(self, preload: tuple[str, ...]) -> None:
        settings = {
            **_SETTINGS,
            **self.settings,
            **({"shared_preload_libraries": ",".join(preload)} if preload else {}),
        }
        options = " ".join(f"-c {k}={v}" for k, v in settings.items())
        started = subprocess.run(
            [
                _bin("pg_ctl"),
                "-D",
                str(self.data),
                "-l",
                str(self.root / "postgres.log"),
                "-w",
                "-o",
                f"-h 127.0.0.1 -p {self.port} -k {self.data} {options}",
                "start",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if started.returncode != 0:
            log = (self.root / "postgres.log").read_text(errors="replace")
            raise RuntimeError(
                f"embedded Postgres did not start on 127.0.0.1:{self.port}:\n{log[-4000:]}"
            )


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # another user's process: running, and not this one's to judge
    return True


#: A directory with no recorded starter is an orphan once it is this old: a starter records itself
#: the moment it has made its directory, so only one made before starters recorded themselves (or
#: whose starter died between the two) has none, and it is never claimed again.
OWNERLESS_AFTER_SECONDS = 24 * 60 * 60


def _orphaned(root: Path) -> bool:
    owner = root / _OWNER
    if owner.is_file():
        return not _running(int(owner.read_text()))
    return time.time() - root.stat().st_mtime > OWNERLESS_AFTER_SECONDS


def _stop_orphans() -> None:
    """Stop every embedded server whose starter is gone, and remove its directory: one whose
    recorded starter is not running, and one with no recorded starter older than
    ``OWNERLESS_AFTER_SECONDS``. One whose starter runs is left alone."""
    for root in Path(tempfile.gettempdir()).glob(f"{_PREFIX}*"):
        if not _orphaned(root):
            continue
        if (root / "data" / "postmaster.pid").exists():
            subprocess.run(
                [_bin("pg_ctl"), "-D", str(root / "data"), "-w", "stop", "-m", "immediate"],
                check=True,
                capture_output=True,
            )
        shutil.rmtree(root)


def start_local_postgres(
    port: int | None = None,
    *,
    preload: tuple[str, ...] = (),
    settings: dict[str, str] | None = None,
) -> LocalPostgres:
    """Init a fresh cluster in a directory of its own and start it on ``127.0.0.1:port`` (a
    leased port when none is given), with ``preload`` as its ``shared_preload_libraries`` and
    ``settings`` over the session's defaults."""
    from tests.port_lease import lease_port

    _stop_orphans()
    root = Path(tempfile.mkdtemp(prefix=_PREFIX))
    (root / _OWNER).write_text(str(os.getpid()))
    pg = LocalPostgres(
        port=lease_port() if port is None else port, root=root, settings=dict(settings or {})
    )
    subprocess.run(
        [_bin("initdb"), "-D", str(pg.data), "-U", "postgres", "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
    )
    pg._start(preload)
    psql = [_bin("psql"), "-h", "127.0.0.1", "-p", str(pg.port), "-U", "postgres"]
    for sql in (
        f"CREATE ROLE {ROLE} LOGIN SUPERUSER PASSWORD '{PASSWORD}'",
        f"CREATE DATABASE {DATABASE} OWNER {ROLE}",
    ):
        subprocess.run([*psql, "-v", "ON_ERROR_STOP=1", "-c", sql], check=True, capture_output=True)
    return pg
