# Copyright (c) 2026 Kenneth Stott
# Canary: 08b7ce96-3cd4-4b0d-927f-34a86375f3af
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The local test platform: what a test session runs on when it needs no Docker stack.

The canonical test platform is the same locally and in CI. A test that needs only Provisa's
control plane, the pg and DuckDB engines, Redis, JDBC or file connectors, or API sources (served by
mock servers started from Python) runs here, on plain addresses like the real services:

- Postgres: the pgserver wheel's PostgreSQL on ``127.0.0.1:${PG_PORT}`` (tests/embedded_pg.py);
- Redis: fakeredis's TCP server on ``127.0.0.1:${REDIS_PORT}`` (tests/embedded_redis.py).

They bind the ports the session leased for the docker stack's postgres and redis
(tests/conftest.py ``_allocate_itest_ports``), so every address the session exports
(``PG_HOST``/``PG_PORT``, ``TENANT_DATABASE_URL``, ``REDIS_URL``, ...) is right as it stands and a
test does not change: only what answers on those ports does.

A session runs on this platform when every test it selected is marked ``local_platform`` (tests
under tests/unit and tests/mvmvp provision themselves either way). ``PROVISA_TEST_PLATFORM=docker``
runs the same tests on the docker stack's real Postgres and Redis instead: the nightly divergence
check. Anything needing an instance of
a heavy server — Trino, Kafka, Neo4j, warehouses, other database servers, the Helm cluster — is
the CI side and keeps the docker stack.
"""

from __future__ import annotations

import os


class LocalPlatformManager:
    """Starts the local platform at collection finish when the session runs on it, and stops it at
    session end."""

    def __init__(self, ports: dict[str, str]) -> None:
        self._ports = ports
        self._postgres = None
        self._redis = None

    def _wanted(self, items) -> bool:
        from tests.conftest import _needs_shared_stack

        if os.environ.get("PYTEST_NO_DOCKER") or not self._ports:
            return False
        return not _needs_shared_stack(items) and any(
            item.get_closest_marker("local_platform") for item in items
        )

    def pytest_collection_finish(self, session):
        if not self._wanted(session.items):
            return
        from tests.embedded_pg import start_local_postgres
        from tests.embedded_redis import start_local_redis

        self._postgres = start_local_postgres(int(self._ports["PG_PORT"]))
        self._redis = start_local_redis(int(self._ports["REDIS_PORT"]))

    def pytest_sessionfinish(self, session, exitstatus):  # pyright: ignore
        if self._redis is not None:
            self._redis.stop()
            self._redis = None
        if self._postgres is not None:
            self._postgres.stop()
            self._postgres = None
