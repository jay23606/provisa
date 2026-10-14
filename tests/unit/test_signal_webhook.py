# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The ``signal`` change signal's receiver: POST /data/sources/{source_id}/signal (REQ-1149).

Each table of the source on the signal (its own, else its source's) is treated as written --
the one path every change to a table takes -- and nothing else is. The caller holds the write
right and reaches each signalled table's domain; a source with no table on the signal is refused
by name, as is a table the source does not have.
"""

# Requirements: REQ-1149

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from provisa.api.data import signal as webhook
from provisa.api.errors import ApiError

_WRITER = {"id": "writer", "capabilities": ["write"], "domain_access": ["sales"]}
_READER = {"id": "reader", "capabilities": ["query_development"], "domain_access": ["*"]}
_ELSEWHERE = {"id": "elsewhere", "capabilities": ["write"], "domain_access": ["hr"]}


def _table(table_id: int, name: str, signal: str | None, domain: str = "sales") -> dict:
    return {
        "id": table_id,
        "source_id": "shop",
        "schema_name": "public",
        "table_name": name,
        "change_signal": signal,
        "domain_id": domain,
    }


@pytest.fixture
def written(monkeypatch):
    tables = [
        _table(1, "orders", None),
        _table(2, "refunds", "ttl"),
        _table(3, "returns", "signal"),
    ]
    state = SimpleNamespace(
        roles={r["id"]: r for r in (_WRITER, _READER, _ELSEWHERE)},
        tables=tables,
    )
    source = SimpleNamespace(id="shop", change_signal="signal")
    seen: list[tuple[int, str, str]] = []

    async def _sources(_state):
        return [source]

    async def _after(_state, *, table_id, table_name, source_id):
        seen.append((table_id, table_name, source_id))

    monkeypatch.setattr("provisa.api.app.state", state, raising=False)
    monkeypatch.setattr("provisa.federation.registry_view.registered_sources", _sources)
    monkeypatch.setattr("provisa.api.data.table_written.after_table_written", _after)
    return seen, source


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(webhook.router)

    @app.exception_handler(ApiError)
    async def _api_error(_request, exc: ApiError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return TestClient(app)


def _post(client, path: str, role: str = "writer"):
    return client.post(path, headers={"X-Provisa-Role": role})


def test_a_signal_marks_each_table_on_the_signal_written(written, client):
    seen, _source = written
    response = _post(client, "/data/sources/shop/signal")
    assert response.status_code == 202, response.text
    # orders inherits the source's signal; returns declares it; refunds is on ttl.
    assert response.json() == {"signalled": ["public.orders", "public.returns"]}
    assert seen == [(1, "orders", "shop"), (3, "returns", "shop")]


def test_a_signal_for_one_table_marks_that_table_only(written, client):
    seen, _source = written
    response = _post(client, "/data/sources/shop/signal?table=public.returns")
    assert response.status_code == 202, response.text
    assert seen == [(3, "returns", "shop")]


def test_a_signal_needs_the_write_right_and_each_tables_domain(written, client):
    seen, _source = written
    assert _post(client, "/data/sources/shop/signal", role="reader").status_code == 403
    assert _post(client, "/data/sources/shop/signal", role="elsewhere").status_code == 403
    assert seen == []


def test_a_signal_nothing_would_act_on_is_refused_by_name(written, client):
    seen, source = written
    missing = _post(client, "/data/sources/nowhere/signal")
    assert missing.status_code == 404
    unknown = _post(client, "/data/sources/shop/signal?table=public.ghosts")
    assert unknown.status_code == 404
    polled = _post(client, "/data/sources/shop/signal?table=public.refunds")
    assert polled.status_code == 409
    assert "on the signal change signal" in polled.text
    source.change_signal = "ttl"  # orders inherited the signal; it no longer does
    assert _post(client, "/data/sources/shop/signal?table=public.orders").status_code == 409
    assert seen == []
