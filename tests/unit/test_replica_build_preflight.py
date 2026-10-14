# Copyright (c) 2026 Kenneth Stott
# Canary: f5742c2d-ea24-4740-aab6-7d8c60d6ab3b
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A table's preflight check (REQ-1165) runs in its replica build, over the rows the build
streams, before the swap. A checked table is no longer fetched whole into a list and landed: its
check reads the build's own batches, lazily, through a bounded queue, and its verdict decides the
swap. ABORT (or a hook that raises) and QUARANTINE leave the replica as it was."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pyarrow as pa
import pytest

from provisa.events.nodes import source_node
from provisa.events.processor import PreflightQuarantine, PreprocessError
from provisa.federation.data_replicator import (
    EngineCaps,
    GroupPart,
    Method,
    ReplicaGroupJob,
    SourceCaps,
    SourceRead,
    TargetCaps,
    TargetLoad,
    TargetWrite,
    data_replicator,
)
from provisa.federation.replica_preflight import QUEUED_BATCHES, RowCheck
from provisa.logs.loader import make_logs_loader
from provisa.mv.preflight import Decision, Verdict
from tests.unit.test_logs_source import (  # the logs source's own fixtures and lines
    SYSLOG_COLUMNS,
    _write,
    kept_state,  # noqa: F401  (fixture)
    root,  # noqa: F401  (fixture)
)

BATCHES, PER_BATCH = 40, 25


class _Target:
    """A store's build table: what was written, and whether it was swapped in or removed."""

    caps = TargetCaps(
        frozenset({TargetWrite.BULK_BATCH}), atomic_swap=True, load=TargetLoad.BULK_STREAM
    )

    def __init__(self):
        self.written = 0
        self.swapped = self.aborted = False

    async def begin(self):
        pass

    async def write(self, batch, rows):
        self.written += len(rows)

    async def swap(self):
        self.swapped = True

    async def abort(self):
        self.aborted = True


class _Engine:
    caps = EngineCaps(reaches_source=False, runs=frozenset())

    async def after_swap(self):
        pass


class _Source:
    """BATCHES batches of PER_BATCH rows; counts how many it has given."""

    caps = SourceCaps(frozenset({SourceRead.CURSOR}))

    def __init__(self, bad_at: int | None = None):
        self.given = 0
        self.bad_at = bad_at

    async def batches(self, _rows):
        for b in range(BATCHES):
            self.given += 1
            rows = [
                {"id": b * PER_BATCH + i, "ok": not (self.bad_at is not None and b == self.bad_at)}
                for i in range(PER_BATCH)
            ]
            yield pa.RecordBatch.from_pylist(rows)


def _check(fn, prior=None):
    return RowCheck(
        fn, node="src.default.t", columns=[("id", "bigint"), ("ok", "boolean")], prior_hash=prior
    )


async def _noop(_copied):
    pass


async def test_the_check_reads_the_whole_table_lazily_a_bounded_number_of_batches_behind():
    source = _Source()
    behind: list[int] = []
    seen: list[int] = []

    def preflight(streams, ctx):
        # An aggregate over every row: it needs the whole table, and gets it.
        for n, row in enumerate(streams["src.default.t"], start=1):
            if n % PER_BATCH == 1:  # the first row of a batch: how far the build is ahead
                behind.append(source.given - (n // PER_BATCH + 1))
            seen.append(row["id"])
        return ctx.ok() if len(seen) == BATCHES * PER_BATCH else ctx.abort("short")

    target = _Target()
    job = data_replicator(source, target, _Engine(), batch_rows=PER_BATCH, check=_check(preflight))
    outcome = await job.run(_noop)
    assert target.swapped and not target.aborted and outcome.rows_copied == BATCHES * PER_BATCH
    assert seen == list(range(BATCHES * PER_BATCH))
    # Never the whole table held for it: the build is at most the queue (and the batch being
    # handed over) ahead of what the check has read.
    assert max(behind) <= QUEUED_BATCHES + 1


async def test_an_abort_mid_build_leaves_the_old_copy_and_names_why():
    def preflight(streams, ctx):
        for row in streams["src.default.t"]:
            if not row["ok"]:
                return ctx.abort(f"row {row['id']} is not ok")
        return ctx.ok()

    target = _Target()
    job = data_replicator(
        _Source(bad_at=3), target, _Engine(), batch_rows=PER_BATCH, check=_check(preflight)
    )
    with pytest.raises(PreprocessError, match="row 75 is not ok"):
        await job.run(_noop)
    assert target.aborted and not target.swapped  # the replica standing is the one before
    assert target.written == BATCHES * PER_BATCH  # the hook decided early; the read ran on


async def test_a_hook_that_raises_is_an_abort():
    def preflight(streams, ctx):
        raise ValueError("cannot read this table")

    target = _Target()
    job = data_replicator(
        _Source(), target, _Engine(), batch_rows=PER_BATCH, check=_check(preflight)
    )
    with pytest.raises(PreprocessError, match="cannot read this table"):
        await job.run(_noop)
    assert target.aborted and not target.swapped


async def test_a_quarantine_holds_without_a_swap():
    def preflight(streams, ctx):
        return Verdict(Decision.QUARANTINE, "too few rows today")

    target = _Target()
    job = data_replicator(
        _Source(), target, _Engine(), batch_rows=PER_BATCH, check=_check(preflight)
    )
    with pytest.raises(PreflightQuarantine, match="too few rows today"):
        await job.run(_noop)
    assert target.aborted and not target.swapped


async def test_a_continue_with_a_reason_swaps_and_warns(caplog):
    def preflight(streams, ctx):
        ctx.warn("a few rows lack an id")
        return ctx.ok()

    target = _Target()
    job = data_replicator(
        _Source(), target, _Engine(), batch_rows=PER_BATCH, check=_check(preflight)
    )
    await job.run(_noop)
    assert target.swapped
    assert "a few rows lack an id" in caplog.text


def test_a_checked_table_is_streamed_never_copied_by_the_engine_statement():
    """The engine's own copy swaps inside its statement: there is no moment to check."""
    engine = SimpleNamespace(caps=EngineCaps(reaches_source=True, runs=frozenset({"statement"})))
    from provisa.federation.data_replicator import EngineRun

    engine.caps = EngineCaps(reaches_source=True, runs=frozenset({EngineRun.STATEMENT}))
    source = SimpleNamespace(
        caps=SourceCaps(frozenset({SourceRead.ENGINE_REACHABLE, SourceRead.CURSOR}))
    )
    target = SimpleNamespace(
        caps=TargetCaps(
            frozenset({TargetWrite.STATEMENT_COPY, TargetWrite.BULK_BATCH}),
            atomic_swap=True,
            load=TargetLoad.BULK_STREAM,
        )
    )
    assert data_replicator(source, target, engine, batch_rows=1).method is Method.ENGINE_STATEMENT
    checked = data_replicator(source, target, engine, batch_rows=1, check=_check(lambda s, c: None))
    assert checked.method is Method.STREAM_BATCHES


async def test_a_logs_table_streams_through_its_check(root, kept_state):  # noqa: F811
    """The logs source's whole read (``_WholeRead``) feeds the group build a batch at a time, and
    the check reads its rows as they come, a bounded number of batches behind the read: the whole
    table is never held as one list for it."""
    files, per_file = 6, 20
    for f in range(files):
        lines = [f"Oct 12 00:{m:02d}:29 host-{f} syslogd[603]: line {m}" for m in range(per_file)]
        _write(root / f"system{f}.log", lines)
    loader = make_logs_loader(SimpleNamespace(tenant_db=kept_state))
    source = SimpleNamespace(
        id="syslog", mapping={"glob": f"{root}/system*.log", "format": "rfc3164"}
    )
    columns = list(SYSLOG_COLUMNS.items())
    reader = loader.replica_group_source(source, ("syslog",), {"syslog": columns})
    given = {"batches": 0}
    whole = reader.batches

    async def counted(batch_rows):
        async for item in whole(batch_rows):
            given["batches"] += 1
            yield item

    reader.batches = counted
    behind: list[int] = []
    read = {"rows": 0}

    def preflight(streams, ctx):
        for row in streams["syslog.default.syslog"]:
            read["rows"] += 1
            behind.append(given["batches"] - (read["rows"] + 1) // 2)
        return ctx.ok()

    check = RowCheck(preflight, node="syslog.default.syslog", columns=columns, prior_hash=None)
    target = _Target()
    built = await ReplicaGroupJob(
        reader, {"syslog": GroupPart(target, _Engine(), check=check)}, batch_rows=2
    ).run(lambda _t, n: _noop(n))
    assert not isinstance(built["syslog"], BaseException), built["syslog"]
    assert target.swapped and target.written == files * per_file == read["rows"]
    assert given["batches"] == files * per_file // 2
    assert max(behind) <= QUEUED_BATCHES + 1  # never the whole read held for the check


async def test_a_checked_table_is_copied_whole_not_kept_in_place_part_by_part():
    """A part kept in place is readable at once, with no swap to check before."""
    from provisa.federation.replica_builds import _kept_in_place

    loader = SimpleNamespace(replica_unit_source=object())
    checked = SimpleNamespace(table_name="syslog", mv_preprocess="def preflight(s, c): return None")
    prepared = {("syslog", "default", "syslog"): (None, checked, None, None)}
    assert await _kept_in_place(SimpleNamespace(), loader, prepared) is False


# --- what the event loop sees: the events land() posted ------------------------------------------

KEY = ("syslog", "default", "syslog")
NODE = source_node(*KEY)
AUTH_KEY = ("syslog", "default", "auth")
AUTH = source_node(*AUTH_KEY)


class _Conn:
    pass


class _Db:
    @asynccontextmanager
    async def acquire(self):
        yield _Conn()


@pytest.fixture
def posted(monkeypatch):
    """The event loop's queue as the build runner writes it: each event posted and where it was
    fanned, and each freshness stamp."""
    from provisa.events import queue

    log: dict = {"events": [], "fanned": [], "refresh": []}

    async def post_event(_conn, *, source_table, event_type, payload):
        log["events"].append((source_table, event_type, payload))
        return len(log["events"])

    async def fan_out(_conn, event_id, targets):
        log["fanned"].append((event_id, list(targets)))

    async def record_refresh(_conn, node, *, at, ok):
        log["refresh"].append((node, ok))

    monkeypatch.setattr(queue, "post_event", post_event)
    monkeypatch.setattr(queue, "fan_out", fan_out)
    monkeypatch.setattr(queue, "record_refresh", record_refresh)
    return log


def _state():
    return SimpleNamespace(
        tenant_db=_Db(),
        replica_nodes={KEY: NODE},
        replica_dependents_of=lambda node: ["shop.mv_errors"] if node == NODE else [],
    )


async def test_a_checked_build_s_abort_is_the_loop_s_error_event_fanned_to_its_readers(
    posted, monkeypatch
):
    from provisa.federation import replica_builds

    async def aborted(_state, _key, _progress):
        raise PreprocessError("row 75 is not ok")

    monkeypatch.setattr(replica_builds, "build_replica", aborted)
    with pytest.raises(PreprocessError):
        await replica_builds.run_build(_state(), KEY, _noop)
    # As land() posted it: the node's error, its reason, fanned to the views that read it.
    assert posted["events"] == [(NODE, "error", {"error": "row 75 is not ok"})]
    assert posted["fanned"] == [(1, ["shop.mv_errors"])]
    assert posted["refresh"] == [(NODE, False)]


async def test_a_checked_build_s_quarantine_is_the_loop_s_quarantine_event_not_fanned(
    posted, monkeypatch
):
    from provisa.federation import replica_builds

    async def held(_state, _key, _progress):
        raise PreflightQuarantine("too few rows today")

    monkeypatch.setattr(replica_builds, "build_replica", held)
    with pytest.raises(PreflightQuarantine):
        await replica_builds.run_build(_state(), KEY, _noop)
    assert posted["events"] == [(NODE, "quarantine", {"reason": "too few rows today"})]
    assert posted["fanned"] == []  # a hold poisons nothing downstream
    assert posted["refresh"] == [(NODE, False)]


async def test_a_build_that_fails_for_another_reason_posts_no_check_event(posted, monkeypatch):
    from provisa.federation import replica_builds

    async def broken(_state, _key, _progress):
        raise ConnectionError("the store refused the connection")

    monkeypatch.setattr(replica_builds, "build_replica", broken)
    with pytest.raises(ConnectionError):
        await replica_builds.run_build(_state(), KEY, _noop)
    assert posted["events"] == [] and posted["refresh"] == [(NODE, False)]


async def test_a_group_build_posts_each_checked_table_s_verdict(posted):
    from provisa.federation.replica_builds import _group_results

    other = AUTH_KEY
    state = _state()
    state.replica_nodes[other] = AUTH
    table = SimpleNamespace(table_name="syslog")
    auth = SimpleNamespace(table_name="auth")
    prepared = {KEY: (None, table, None, None), other: (None, auth, None, None)}
    nodes = {KEY: NODE, other: AUTH}
    built = {"syslog": PreprocessError("bad host"), "auth": PreflightQuarantine("held")}
    results = await _group_results(state, prepared, nodes, built, {})
    assert isinstance(results[KEY], PreprocessError) and isinstance(
        results[other], PreflightQuarantine
    )
    assert posted["events"] == [
        (NODE, "error", {"error": "bad host"}),
        (AUTH, "quarantine", {"reason": "held"}),
    ]
    assert posted["fanned"] == [(1, ["shop.mv_errors"])]
