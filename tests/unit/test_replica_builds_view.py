# Copyright (c) 2026 Kenneth Stott
# Canary: 45cb81a8-09a8-4c11-8c55-0ceddf42677f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1915: what an operator sees of a replica's build — its state, how it copies (method and
load kind, known from the moment it starts), rows copied and the rate so far, its last error."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from provisa.api.admin._replica_builds import build_view

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


def _record(**kw):
    base = dict(
        key=("src", "public", "orders"),
        build_state="idle",
        requested_reason=None,
        build_started_at=None,
        build_method=None,
        load_kind=None,
        rows_copied=None,
        completed_rows=None,
        completed_at=None,
        next_refresh_at=None,
        last_error=None,
        last_error_code=None,
        last_error_params=None,
        failed_attempts=0,
        failed_at=None,
        waiting_on=None,
        retired_at=None,
        feed_down_since=None,
        feed_error=None,
        delta_skipped=None,
        delta_cursor=None,
        build_notes=[],
        verified_at=None,
        build_wait=None,
        build_progress=None,
        partial=False,
        index_state=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_running_row_copy_build_shows_its_method_progress_and_rate():
    view = build_view(
        _record(
            build_state="building",
            requested_reason="model",
            build_started_at=NOW - timedelta(seconds=100),
            build_method="stream_batches",
            load_kind="row_copy",
            rows_copied=3_800_000,
        ),
        NOW,
    )
    assert (view["state"], view["method"], view["load_kind"]) == (
        "building",
        "stream_batches",
        "row_copy",
    )
    assert view["rows_copied"] == 3_800_000 and view["rows_per_second"] == 38_000.0
    assert view["started_at"] == "2026-10-02T11:58:20+00:00"
    assert (view["source_id"], view["schema_name"], view["table_name"]) == (
        "src",
        "public",
        "orders",
    )


def test_a_build_with_no_progress_yet_has_no_rate():
    started = _record(build_state="building", build_started_at=NOW, rows_copied=0)
    assert build_view(started, NOW)["rows_per_second"] is None


def test_a_finished_build_has_no_running_rate_and_keeps_its_last_method():
    view = build_view(
        _record(
            build_started_at=NOW - timedelta(seconds=10),
            build_method="engine_statement",
            load_kind="bulk_stream",
            rows_copied=500,
            completed_at=NOW,
        ),
        NOW,
    )
    assert view["state"] == "idle" and view["rows_per_second"] is None
    assert view["method"] == "engine_statement" and view["completed_at"] is not None


def test_a_failed_build_shows_its_error_and_a_waiting_one_says_why():
    failed = build_view(
        _record(
            build_state="failed",
            last_error="the answer read for the replica of g.orders is not valid JSON: ...",
            last_error_code="replication.answer_not_json",
            last_error_params={"table": "g.orders", "cause": "x", "kib": 64, "before_byte": 9},
            failed_attempts=3,
        ),
        NOW,
    )
    assert (failed["state"], failed["failed_attempts"]) == ("failed", 3)
    assert failed["last_error"].startswith("the answer read for the replica of g.orders")
    assert failed["last_error_code"] == "replication.answer_not_json"
    assert failed["last_error_params"]["table"] == "g.orders"
    # A driver's own error has no code: its text is all there is.
    plain = build_view(_record(build_state="failed", last_error="source down"), NOW)
    assert (plain["last_error"], plain["last_error_code"]) == ("source down", None)
    # Why a requested build has not started: the code, and its English text.
    waiting = build_view(
        _record(build_state="requested", waiting_on="replication.waiting_engine_jobs"), NOW
    )
    assert waiting["waiting_on_code"] == "replication.waiting_engine_jobs"
    assert waiting["waiting_on"] == (
        "the engine is at its background job cap (replication.engine_jobs)"
    )
    assert build_view(_record(), NOW)["waiting_on"] is None


def test_a_replica_the_model_no_longer_declares_is_shown_as_retired():
    view = build_view(_record(build_state="idle", completed_at=NOW, retired_at=NOW), NOW)
    assert view["state"] == "retired"


def test_a_build_that_had_something_to_say_shows_its_note():
    params = {"count": 2, "ids": ["m1", "m9"], "more": 0}
    view = build_view(
        _record(
            completed_at=NOW,
            build_notes=[{"code": "replication.unreadable_messages", "params": params}],
        ),
        NOW,
    )
    assert view["build_notes"] == [{"code": "replication.unreadable_messages", "params": params}]


def test_a_copy_its_probe_found_unchanged_shows_when_it_was_checked():
    view = build_view(_record(completed_at=NOW, verified_at=NOW), NOW)
    assert view["verified_at"] == view["completed_at"] and view["verified_at"] is not None
    assert build_view(_record(completed_at=NOW), NOW)["verified_at"] is None


def test_a_build_with_nothing_to_say_shows_no_note():
    view = build_view(_record(completed_at=NOW), NOW)
    assert view["build_notes"] == []


def test_a_running_build_is_shown_with_the_last_whole_builds_rows():
    """What its progress is measured against; None for a table never built whole."""
    started = NOW - timedelta(seconds=10)
    view = build_view(
        _record(
            build_state="building",
            build_started_at=started,
            rows_copied=12400,
            completed_rows=20000,
        ),
        NOW,
    )
    assert (view["rows_copied"], view["completed_rows"]) == (12400, 20000)
    assert build_view(_record(build_state="building"), NOW)["completed_rows"] is None


def test_a_build_waiting_out_a_throttle_says_who_asked_and_for_how_long():
    from datetime import UTC, datetime

    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    wait = {"by": "Microsoft", "seconds": 87, "until": "2026-10-10T12:01:27+00:00"}
    assert build_view(_record(build_state="building", build_wait=wait), now)["wait"] == wait
    # A build that is not running is not waiting, whatever its record was left holding.
    assert build_view(_record(build_state="idle", build_wait=wait), now)["wait"] is None


def test_a_build_that_lands_a_part_at_a_time_says_how_far_it_has_got():
    """A mail source's first build can be read while it runs: the view says it is partial and
    how many of the source's mailboxes have been read to their end."""
    from datetime import UTC, datetime

    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    progress = {"done": 3, "total": 40, "unit": "mailboxes", "first": True}
    running = build_view(
        _record(build_state="building", build_progress=progress, partial=True, completed_at=now),
        now,
    )
    assert running["progress"] == progress and running["partial"] is True
    # Once it has ended, and for any other build, there is nothing to say.
    done = build_view(_record(build_state="idle", build_progress=progress, completed_at=now), now)
    assert done["progress"] is None and done["partial"] is False


def test_a_replica_shows_each_index_its_landing_asked_for_and_how_it_stands():  # REQ-2015
    state = {
        "for": "2026-10-15T00:00:00+00:00",
        "wanted": [
            {"name": "ix_pk", "columns": ["id"], "primary": True},
            {"name": "ix_cust", "columns": ["customer_id"], "primary": False},
            {"name": "ix_region", "columns": ["region"], "primary": False},
        ],
        "built": ["ix_cust"],
        "failed": {
            "ix_pk": {
                "error": "the replica's rows repeat the key (id)",
                "code": "replica.index_duplicate_key",
                "columns": ["id"],
            }
        },
    }
    view = build_view(_record(index_state=state), datetime.now(UTC))
    assert [(i["name"], i["state"]) for i in view["indexes"]] == [
        ("ix_pk", "failed"),
        ("ix_cust", "built"),
        ("ix_region", "pending"),
    ]
    failed = view["indexes"][0]
    assert failed["primary"] is True and failed["error_code"] == "replica.index_duplicate_key"
    assert failed["error"].startswith("the replica's rows repeat")


def test_a_replica_whose_landing_asked_for_no_index_shows_none():
    assert build_view(_record(), datetime.now(UTC))["indexes"] == []
