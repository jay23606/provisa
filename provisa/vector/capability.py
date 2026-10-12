# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""Source vector-capability detection (REQ-422).

When a source's driver connects (at boot and at registration, ``executor.pool.SourcePool.add``)
its native vector capability is detected and held with its driver: what its own SQL can compute a
similarity search with (similarity.lower). A PostgreSQL source has it when the pgvector extension
is installed, probed on the connection; Snowflake's SQL always has its VECTOR functions. Every
other source has none, and a search over it is computed by the federation engine.

MongoDB, Qdrant and Cosmos DB search natively in a query form, not a SQL scalar: their own
nearest-neighbour search is a pipeline or search table (REQ-1980, REQ-1982, REQ-1983).
"""

# Requirements: REQ-422

from __future__ import annotations

from typing import Any

_PGVECTOR_PROBE = "SELECT 1 FROM pg_extension WHERE extname = 'vector'"


async def detect_vector_capability(dialect: str, driver: Any) -> str | None:  # REQ-422
    """``"pgvector"`` for a PostgreSQL source with the extension, ``"snowflake"`` for Snowflake,
    else None. ``driver`` is the source's connected direct driver."""
    if dialect == "postgres":
        result = await driver.execute(_PGVECTOR_PROBE)
        return "pgvector" if result.rows else None
    if dialect == "snowflake":
        return "snowflake"
    return None
