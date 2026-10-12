# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Node source's worker under each real runtime (REQ-1984): the pinned runtime is fetched as a
source's would be and runs Provisa's host on a bundle. Rows, timestamps and big integers, a
command's value, the code's own error, a stream stopped by its subscriber, and a deadline that
stops a call, alike on Node, Bun and Deno; Deno reads nothing outside the bundle."""

# Requirements: REQ-1984, REQ-1882
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from provisa.codesource import worker as w
from provisa.core import request_deadline
from provisa.node.worker import host_command
from provisa.runtime_deps.code_runtimes import CodeRuntimeResolver

pytestmark = [pytest.mark.integration]

BUNDLE = """
export async function orders(customerId, since) {
  return [{ id: 1, customer: customerId, placed: new Date("2026-01-02T03:04:05.000Z"),
            since: since ?? null, big: 9007199254740993n, note: undefined }];
}
export function many(count) {
  return Array.from({ length: count }, (_, i) => ({ i }));
}
export async function* ticks() {
  for (let n = 0; ; n++) {
    yield { tick: n };
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}
export async function* forever() {
  await new Promise(() => {});
}
export async function cancelOrder(id) {
  return { cancelled: id };
}
export async function boom() {
  throw new Error("no such customer");
}
export async function outside() {
  const fs = await import("node:fs");
  return [{ text: fs.readFileSync("/etc/hosts", "utf8").length }];
}
"""


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    return tmp_path_factory.mktemp("runtime-deps")


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"type": "module", "main": "orders.js"}))
    (tmp_path / "orders.js").write_text(BUNDLE)
    return tmp_path


def _start(runtime, cache, bundle):
    executable = CodeRuntimeResolver(cache_root=cache).resolve(runtime)
    command = host_command(runtime=runtime, executable=executable, bundle=bundle, egress=[])
    started = w.Worker(f"{runtime}-src", "h", command)
    started.start()
    return started


@pytest.fixture(params=["node", "bun", "deno"])
def worker(request, cache, bundle):
    started = _start(request.param, cache, bundle)
    yield request.param, started
    started.stop()


def test_rows_and_their_values_come_back_in_their_own_types(worker):
    _, started = worker
    assert set(started.exports) >= {"orders", "many", "ticks", "cancelOrder", "boom"}
    since = datetime(2025, 12, 1, tzinfo=UTC)
    [[row]] = list(started.rows("orders", "table", ["acme", since]))
    assert row == {
        "id": 1,
        "customer": "acme",
        "placed": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "since": since,
        "big": 9007199254740993,
        "note": None,
    }


def test_a_large_table_comes_in_batches(worker):
    _, started = worker
    assert [len(b) for b in started.rows("many", "table", [2500])] == [1000, 1000, 500]


def test_a_commands_value_and_the_codes_own_error(worker):
    _, started = worker
    assert started.command("cancelOrder", [7]) == {"cancelled": 7}
    with pytest.raises(w.CodeFailed, match="no such customer"):
        list(started.rows("boom", "table", []))


def test_a_stream_its_subscriber_leaves_is_stopped_and_the_worker_serves_on(worker):
    _, started = worker
    rows = started.rows("ticks", "stream", [])
    assert [next(rows), next(rows), next(rows)] == [[{"tick": 0}], [{"tick": 1}], [{"tick": 2}]]
    rows.close()
    assert started.ping()


def test_a_deadline_stops_a_call_that_never_answers(worker):
    _, started = worker
    with pytest.raises(TimeoutError):
        with request_deadline.within(0.5):
            list(started.rows("forever", "stream", []))
    assert started.ping()


def test_deno_reads_nothing_outside_the_bundle(cache, bundle):
    started = _start("deno", cache, bundle)
    try:
        with pytest.raises(w.CodeFailed, match="/etc/hosts"):
            list(started.rows("outside", "table", []))
    finally:
        started.stop()
