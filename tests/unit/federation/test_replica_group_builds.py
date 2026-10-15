# Copyright (c) 2026 Kenneth Stott
# Canary: 05827a0f-bd7d-4b90-90a6-7ab427a52690
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
# ruff: noqa: F811  (the `wiring` fixture is imported and named as a test's argument)

"""REQ-1915: the replicas one read of a source gives are assembled into one build -- each
table its own address, build table, record of how it copies and stamp on its freshness node,
around ONE read. The fakes are the single build's."""

from types import SimpleNamespace

import pyarrow as pa
import pytest

from provisa.federation import replica_builds
from provisa.federation.data_replicator import SourceCaps, SourceRead
from tests.unit.federation.test_replica_builds import (  # noqa: F401  (wiring is a fixture)
    _Backend,
    _col,
    _source,
    _state,
    _Target,
    wiring,
)

pytestmark = pytest.mark.unit

NAMES = ("messages", "threads", "attachments")
#: The types the module declares, before a fixture narrows them to this file's fake adapter.
REAL_GROUP_READ_TYPES = replica_builds.GROUP_READ_TYPES
KEYS = [("s1", "public", name) for name in NAMES]


def _table(name):
    return SimpleNamespace(
        id=sum(map(ord, name)),  # the table's registered id
        source_id="s1",
        schema_name="public",
        table_name=name,
        change_signal=None,
        watermark_column=None,
        probe_type=None,
        landing_filter=None,
        live=None,
        row_materialize=False,
        columns=[_col("id", "bigint", pk=True), _col("name", "text")],
    )


class _Targets(_Backend):
    """A store that keeps each table's build table apart."""

    def __init__(self):
        super().__init__()
        self.targets: dict[str, _Target] = {}

    def replica_target(self, state, *, address, args, engine):
        target = _Target([], address, args)
        self.targets[address.table] = target
        return target


class _GroupRead:
    caps = SourceCaps(frozenset({SourceRead.CURSOR}))

    def __init__(self, tables, columns, seen, *, fail=False):
        self._tables, self._columns, self._fail = tables, columns, fail
        seen["asked"] = (tuple(tables), {t: list(c) for t, c in columns.items()})
        seen["reads"] = seen.get("reads", 0)
        self._seen = seen

    def notes(self):
        return []

    async def batches(self, batch_rows):
        self._seen["reads"] += 1
        for n, table in enumerate(self._tables):
            if self._fail and n == 1:
                raise RuntimeError("the source stopped answering")
            yield table, pa.RecordBatch.from_pylist([{"id": n, "name": table}])


@pytest.fixture
def group(wiring, monkeypatch):
    """The single build's wiring, with an adapter that gives NAMES from one read and the
    freshness node's stamps recorded."""
    seen = wiring
    seen["stamps"] = []
    seen["fail"] = False

    def loader(source, table):
        raise AssertionError("a group build never reads one table alone")

    loader.replica_group = lambda source, table: NAMES if table.table_name in NAMES else None
    loader.replica_group_source = lambda source, tables, columns: _GroupRead(
        tables, columns, seen, fail=seen["fail"]
    )
    monkeypatch.setattr(
        "provisa.events.app_wiring.build_adapter_loaders", lambda s, e: {"openapi": loader}
    )
    monkeypatch.setattr(replica_builds, "GROUP_READ_TYPES", frozenset({"openapi"}))

    async def record_refresh(conn, node, *, at, ok):
        seen["stamps"].append((node, ok))

    monkeypatch.setattr("provisa.events.queue.record_refresh", record_refresh)
    started = seen.setdefault("all_started", [])

    async def _started(conn, key, *, method, load_kind):
        started.append((key, method, load_kind))

    monkeypatch.setattr("provisa.federation.replica_state.record_started", _started)
    return seen


def _group_state(backend, names=NAMES):
    return _state(backend, tables=[_table(n) for n in (*names, "folders")])


async def _noop(key, rows):
    return None


async def test_the_tables_of_one_read_are_found_among_the_declared_replicas(group):
    group["record"] = SimpleNamespace(retired_at=None)
    state = _group_state(_Targets())
    assert await replica_builds.group_of(state, KEYS[0]) == sorted(KEYS[1:])
    assert await replica_builds.group_of(state, ("s1", "public", "folders")) is None
    # A table the model does not declare, or one with no replica, is no sibling.
    assert await replica_builds.group_of(_group_state(_Targets(), NAMES[:2]), KEYS[0]) == [KEYS[1]]
    group["record"] = None
    assert await replica_builds.group_of(state, KEYS[0]) == []
    group["record"] = SimpleNamespace(retired_at="yesterday")
    assert await replica_builds.group_of(state, KEYS[0]) == []


async def test_a_source_that_gives_no_group_has_none(wiring):
    wiring["record"] = SimpleNamespace(retired_at=None)
    assert await replica_builds.group_of(_group_state(_Targets()), KEYS[0]) is None


async def test_one_read_builds_each_claimed_table_at_its_own_address(group):
    backend = _Targets()
    progress: list = []

    async def seen_progress(key, rows):
        progress.append((key, rows))

    built = await replica_builds.build_group(_group_state(backend), KEYS, seen_progress)

    assert group["reads"] == 1
    asked_tables, asked_columns = group["asked"]
    assert asked_tables == NAMES  # the claimed tables, and no other of the read's
    assert asked_columns["threads"] == [("id", "bigint"), ("name", "text")]
    assert len(backend.targets) == 3
    for target in backend.targets.values():
        assert target.log[0] == "begin" and target.log[-1] == "swap"
    for key in KEYS:
        outcome = built[key]
        assert outcome.rows_copied == 1 and outcome.changed
        assert outcome.definition_hash and outcome.built_columns == [
            ["id", "bigint"],
            ["name", "text"],
        ]
    assert sorted(k for k, _m, _l in group["all_started"]) == sorted(KEYS)
    assert {m for _k, m, _l in group["all_started"]} == {"stream_batches"}
    assert sorted(progress) == sorted((key, 1) for key in KEYS)
    assert [ok for _node, ok in group["stamps"]] == [True, True, True]


async def test_only_the_tables_claimed_are_built(group):
    backend = _Targets()
    built = await replica_builds.build_group(_group_state(backend), KEYS[:2], _noop)
    assert set(built) == set(KEYS[:2]) and len(backend.targets) == 2
    assert group["asked"][0] == NAMES[:2]


async def test_a_read_that_fails_swaps_nothing_and_stamps_every_table_as_failed(group):
    group["fail"] = True
    backend = _Targets()
    with pytest.raises(RuntimeError, match="stopped answering"):
        await replica_builds.build_group(_group_state(backend), KEYS, _noop)
    for target in backend.targets.values():
        assert "swap" not in target.log and target.log[-1] == "abort"
    assert [ok for _node, ok in group["stamps"]] == [False, False, False]


async def test_a_table_the_model_no_longer_declares_is_answered_and_the_rest_are_built(group):
    backend = _Targets()
    state = _group_state(backend, NAMES[:2])  # attachments is gone from the model
    built = await replica_builds.build_group(state, KEYS, _noop)
    assert isinstance(built[KEYS[2]], replica_builds.ReplicaTableGone)
    assert built[KEYS[0]].rows_copied == 1 and built[KEYS[1]].rows_copied == 1
    assert group["asked"][0] == NAMES[:2] and len(backend.targets) == 2


async def test_the_runner_is_given_the_group_calls():
    import inspect

    source = inspect.getsource(replica_builds.make_runner)
    assert "group_of=lambda key: group_of(state, key)" in source
    assert "build_group=lambda keys, progress: build_group(state, keys, progress)" in source


async def test_a_table_answered_before_a_read_that_fails_is_handed_back_with_its_own_reason(group):
    from provisa.federation.data_replicator import GroupReadFailed

    group["fail"] = True
    state = _group_state(_Targets(), NAMES[:2])  # attachments is gone from the model
    with pytest.raises(GroupReadFailed, match="stopped answering") as failed:
        await replica_builds.build_group(state, KEYS, _noop)
    assert isinstance(failed.value.cause, RuntimeError)
    assert list(failed.value.settled) == [KEYS[2]]
    assert isinstance(failed.value.settled[KEYS[2]], replica_builds.ReplicaTableGone)


async def test_a_source_type_that_declares_no_group_looks_no_adapter_up(wiring, monkeypatch):
    def never(state, engine):
        raise AssertionError("no adapter is built for a source type with no group read")

    monkeypatch.setattr("provisa.events.app_wiring.build_adapter_loaders", never)
    monkeypatch.setattr(replica_builds, "GROUP_READ_TYPES", frozenset({"microsoft_365"}))
    wiring["record"] = SimpleNamespace(retired_at=None)
    assert await replica_builds.group_of(_group_state(_Targets()), KEYS[0]) is None


def _mail_loader(source_type):
    if source_type == "microsoft_365":
        from provisa.microsoft365.loader import make_microsoft365_loader

        return make_microsoft365_loader(None)  # type: ignore[arg-type]
    from provisa.google_workspace.loader import make_google_workspace_loader

    return make_google_workspace_loader(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("source_type", ["microsoft_365", "google_workspace"])
def test_the_source_types_that_read_in_groups_are_the_ones_whose_loader_says_so(source_type):
    loader = _mail_loader(source_type)
    assert source_type in replica_builds.GROUP_READ_TYPES
    assert callable(loader.replica_group) and callable(loader.replica_group_source)
    assert callable(loader.replica_unit_source)


# --- a source whose reader gives units is kept in place, a part at a time ---


class _UnitRead:
    """Gives two parts of one mailbox and says the source names two."""

    unit = "mailboxes"

    def __init__(self, tables, seen):
        self._tables, self._seen = tables, seen
        self.total = 0
        seen["unit_tables"] = tuple(tables)

    def notes(self):
        return []

    async def keep(self, account, links):
        self._seen.setdefault("kept", []).append((account, dict(links)))

    async def forget(self, account):
        raise AssertionError("nothing is read again from its start here")

    async def committed(self):
        self._seen["committed"] = True

    async def units(self):
        from provisa.core.canonical_mail import Unit

        self.total = 2
        yield Unit("a@x.test", rows={"messages": [{"id": 1, "name": "m"}]})
        yield Unit(
            "a@x.test",
            rows={"threads": [{"id": 9, "name": "t"}]},
            links={"": "where-it-reached"},
            last=True,
        )


@pytest.fixture
def in_place(group, monkeypatch):
    seen = group
    seen["applied"], seen["partial"], seen["parts"] = [], [], []
    loader = None

    def make(source, tables, columns):
        return _UnitRead(tables, seen)

    from provisa.core import canonical_mail as cm
    from provisa.events import app_wiring

    loader = app_wiring.build_adapter_loaders(None, None)["openapi"]
    loader.replica_unit_source = make
    loader.replica_key_columns = cm.key_columns
    loader.replica_stamp_column = cm.LANDED_AT

    async def record_partial(conn, key, **kw):
        seen["partial"].append((key, kw["store"], kw["built_columns"]))
        return True

    async def record_parts(conn, key, **kw):
        seen["parts"].append((key, kw))

    async def row_count(state, key):
        return {"messages": 1, "threads": 1, "attachments": 0}[key[2]]

    monkeypatch.setattr("provisa.federation.replica_state.record_partial", record_partial)
    monkeypatch.setattr("provisa.federation.replica_state.record_parts", record_parts)
    monkeypatch.setattr("provisa.federation.replica_hot._row_count", row_count)

    async def invalidate_tables(state, table_ids):
        seen.setdefault("dropped", []).append(sorted(table_ids))
        return 0

    monkeypatch.setattr("provisa.cache.tenancy.invalidate_tables", invalidate_tables)
    return seen


def _in_place_state(seen):
    state = _group_state(_Targets())

    async def apply(group):
        seen["applied"].append([(c.table, len(c.events), c.pk_columns) for c in group])

    state.federation_engine.apply_change_group = apply
    return state


async def test_a_source_that_gives_units_is_kept_in_place_and_swaps_nothing(in_place):
    state = _in_place_state(in_place)
    built = await replica_builds.build_group(state, KEYS, _noop)
    backend = state.federation_engine.engine.backend
    assert backend.targets == {}  # no build table, no swap
    assert in_place.get("reads", 0) == 0  # the whole read was not asked for
    assert in_place["unit_tables"] == NAMES
    made, first_part, second_part = in_place["applied"]
    # Every table is made before any part lands, so one no part writes to is an empty replica.
    assert sorted(table for table, _n, _k in made) == sorted(f"s1__public__{n}" for n in NAMES)
    assert all(count == 0 for _t, count, _k in made)
    assert [(t, n) for t, n, _k in first_part] == [("s1__public__messages", 1)]
    assert first_part[0][2] == ["provider", "account", "id"]  # kept by the mail table's key
    assert [(t, n) for t, n, _k in second_part] == [("s1__public__threads", 1)]
    # Where the read reached is kept after its rows were written.
    assert in_place["kept"] == [("a@x.test", {"": "where-it-reached"})]
    for key in KEYS:
        outcome = built[key]
        assert outcome.method == "apply_units" and outcome.changed
        assert outcome.rows_copied == {"messages": 1, "threads": 1, "attachments": 0}[key[2]]
        assert outcome.definition_hash and outcome.committed is not None
    assert {m for _k, m, _l in in_place["all_started"]} == {"apply_units"}
    assert [ok for _node, ok in in_place["stamps"]] == [True, True, True]


async def test_a_first_build_is_a_replica_as_soon_as_its_first_part_has_landed(in_place):
    await replica_builds.build_group(_in_place_state(in_place), KEYS, _noop)
    # No table had a copy in this store: each is recorded as readable, once, in this store.
    assert sorted(key for key, _s, _c in in_place["partial"]) == sorted(KEYS)
    assert {store for _k, store, _c in in_place["partial"]} == {"store-a"}
    # And says how many of the source's mailboxes have been read to their end.
    assert {(kw["done"], kw["total"], kw["unit"], kw["first"]) for _k, kw in in_place["parts"]} == {
        (1, 2, "mailboxes", True)
    }


async def test_a_replica_built_from_another_definition_is_copied_whole_again(in_place):
    """Changed columns are not something a part at a time can bring about."""
    in_place["record"] = SimpleNamespace(
        content_hash=None, definition_hash="another", exists_in=lambda store: True
    )
    state = _in_place_state(in_place)
    await replica_builds.build_group(state, KEYS, _noop)
    assert in_place["applied"] == [] and in_place["reads"] == 1
    assert len(state.federation_engine.engine.backend.targets) == 3


async def test_answers_cached_from_a_table_are_dropped_when_parts_land_in_it(in_place):
    """What was answered from the table before a part landed is no longer what it holds. The
    table that no part wrote to keeps its cached answers."""
    state = _in_place_state(in_place)
    ids = {t.table_name: t.id for t in state.config.tables}
    await replica_builds.build_group(state, KEYS, _noop)
    dropped = {table_id for call in in_place["dropped"] for table_id in call}
    assert dropped == {ids["messages"], ids["threads"]}


async def test_a_google_workspace_mail_replica_is_kept_in_place(in_place, monkeypatch):
    """Google Workspace's own adapter, looked up as the module declares the group-read types:
    its mailboxes are read a part at a time and kept in place, as Microsoft 365's are."""
    loader = _mail_loader("google_workspace")
    loader.replica_unit_source = lambda source, tables, columns: _UnitRead(tables, in_place)
    monkeypatch.setattr(
        "provisa.events.app_wiring.build_adapter_loaders", lambda s, e: {"google_workspace": loader}
    )
    monkeypatch.setattr(replica_builds, "GROUP_READ_TYPES", REAL_GROUP_READ_TYPES)
    state = _in_place_state(in_place)
    state.config.sources[0].type = "google_workspace"
    built = await replica_builds.build_group(state, KEYS, _noop)
    assert state.federation_engine.engine.backend.targets == {}  # no build table, no swap
    assert in_place["unit_tables"] == NAMES
    assert {outcome.method for outcome in built.values()} == {"apply_units"}
