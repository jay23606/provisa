# Copyright (c) 2026 Kenneth Stott
# Canary: 3f7a2c91-6e4b-4d18-a5c0-9b2e8d1f6a47
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A native engine's close releases its persistent runtime (REQ-825).

The runtime holds what it attached -- a DuckDB-attached Postgres source keeps a pool of its own --
so a runtime left open at shutdown kept those connections until the process exited. Close
releases it and forgets its attaches; a later use builds a new runtime."""

# Requirements: REQ-825

from __future__ import annotations

from provisa.federation.native_backend import NativeEngineBackend


class _Runtime:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Backend(NativeEngineBackend):
    def __init__(self) -> None:
        super().__init__(engine=object())
        self.built: list[_Runtime] = []

    def _new_runtime(self) -> _Runtime:
        runtime = _Runtime()
        self.built.append(runtime)
        return runtime


def test_close_releases_the_runtime_and_a_later_use_builds_a_new_one():
    backend = _Backend()
    first = backend._store_runtime()
    backend._attached.add(("src", "public", "orders"))
    backend.close(state=None)
    assert first.closed
    assert backend._attached == set()
    second = backend._store_runtime()
    assert second is not first and not second.closed


def test_close_with_no_runtime_built_is_a_no_op():
    backend = _Backend()
    backend.close(state=None)
    assert backend.built == []
