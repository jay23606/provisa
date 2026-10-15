# Copyright (c) 2026 Kenneth Stott
# Canary: 855f511c-aa50-40b0-971a-cfc39fc1eb46
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The ``cache_ttl`` value rules (REQ-2003, REQ-2031).

One integer of seconds on a source or a table, a table with none inheriting its source's:

* ``N >= 0`` -- the table's replica (or kept rows) is current for N seconds; 0 means 0
  (REQ-2003), never "unset";
* ``-1`` -- never expires: the table lands once and its replica is never stale after that. Its
  reads are always answered from the replica, and a source whose tables all never expire and
  have landed is never contacted (REQ-2031).

Any other negative value is refused.
"""

# Requirements: REQ-2003, REQ-2031

from __future__ import annotations

import datetime

#: The table lands once and its replica never goes stale.
NEVER_EXPIRES = -1


def cache_ttl_refusal(value: int | None) -> str | None:
    """The error for an illegal ``cache_ttl``, else None: not set, -1, or 0 and more are legal."""
    if value is None or value >= NEVER_EXPIRES:
        return None
    return f"cache_ttl must be -1 (never expires), 0 or more seconds, or not set; got {value}"


def expires_after(now: datetime.datetime, ttl: int) -> datetime.datetime:
    """When something kept at ``now`` for ``ttl`` seconds expires: never (the latest time there
    is, in ``now``'s zone) for -1."""
    if ttl == NEVER_EXPIRES:
        return datetime.datetime.max.replace(tzinfo=now.tzinfo)
    return now + datetime.timedelta(seconds=ttl)


def check_cache_ttl(value: int | None) -> int | None:
    """``value`` when it is a legal ``cache_ttl``; raises ValueError otherwise."""
    refused = cache_ttl_refusal(value)
    if refused is not None:
        raise ValueError(refused)
    return value
