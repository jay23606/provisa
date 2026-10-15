# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Triggers on a table: what fires on a table's change or event-loop event (REQ-2054).

A trigger ``on: {table, event}`` says when; what it runs -- a command, a SQL statement, a
webhook -- runs as any trigger's run does (``trigger_runs.run_trigger``), once per firing, in the
background. What fires:

- ``change``, once per burst of changes the table's change signal reports. A table read from its
  whole-table replica changes when a build of it lands rows that differ from the last
  (``replica_builds.make_runner``): the native feeds, the signal webhook and a write through
  Provisa each ask for that build, and what runs reads what it landed. A table read live changes
  when Provisa writes it or its signal says so (:func:`source_changed`). A table landed from a
  Kafka or Debezium feed changes when a batch of its events lands, and the batch is given.
- ``error`` and ``quarantine``, each time the event loop posts one for the table's node.

A run's own write is a change like any other, so triggers chain; a run that is refused or fails
wrote nothing, so nothing fires after it. Only an org's prod triggers fire, as only its prod
schedules run. No trigger is installed in any source database.
"""

# Requirements: REQ-2054

from __future__ import annotations

from typing import Any

from provisa.core.connection_loop import spawn_background

ReplicaKey = tuple[str, str, str]


def table_changed(state: Any, key: ReplicaKey, *, changes: list[dict] | None = None) -> None:
    """``key``'s table changed: each enabled trigger on its change fires, given the table and,
    where the signal carried it, the batch."""
    table = ".".join(key)
    spawn_background(
        _fire(state, table, "change", {"table": table, "changes": changes}),
        name=f"triggers:change:{table}",
    )


def table_event(state: Any, key: ReplicaKey, event: str, payload: dict) -> None:
    """The event loop posted ``event`` (``error`` or ``quarantine``) for ``key``'s table: each
    enabled trigger on it fires, given the table, the event and its reason and error."""
    table = ".".join(key)
    given = {
        "table": table,
        "event": event,
        "reason": payload.get("reason"),
        "error": payload.get("error"),
    }
    spawn_background(_fire(state, table, event, given), name=f"triggers:{event}:{table}")


async def source_changed(state: Any, table_id: int, source_id: str, reason: str) -> None:
    """A change to the registered table ``table_id`` that its change signal or a write reported.
    A table read from its whole-table replica asks for a build, and its triggers fire when the
    build lands; any other's fire now."""
    from provisa.federation import replica_builds
    from provisa.federation.registry_view import registered_tables

    if await replica_builds.request_if_replicated(state, table_id, source_id, reason):
        return
    table = {t.id: t for t in await registered_tables(state)}[table_id]
    table_changed(state, (source_id, table.schema_name, table.table_name))


async def _fire(state: Any, table: str, event: str, given: dict) -> None:
    """Run each enabled trigger on ``event`` for ``table``, one after another, in this org's prod."""
    from provisa.core.environments import PROD
    from provisa.core.repositories import scheduled_trigger as trigger_repo
    from provisa.core.request_context import require_current_org
    from provisa.scheduler.trigger_runs import run_trigger

    if state._active_runtime().env != PROD:
        return  # an environment's triggers are definitions that run once promoted
    async with state.model_db.acquire() as conn:
        triggers = await trigger_repo.on_table(conn, table, event)
    org_id = require_current_org()
    for trigger in triggers:
        await run_trigger(trigger, org_id, given=given, fired_by=f"{event}:{table}")
