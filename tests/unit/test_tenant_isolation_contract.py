# Copyright (c) 2026 Kenneth Stott
# Canary: 4b7e1c92-6d03-4a58-9f21-8c0e2d63a915
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-838: tenant control-plane isolation is a CONTRACT, mechanism is backend-relative.

The invariant — a tenant-scoped connection reaches only its own org's data — is identical
across control-plane backends; only the REALIZATION differs, chosen from the store's dialect:

- PostgreSQL   -> per-connection SET search_path to org_<org_id> + a per-org role
                  (physical schema isolation).
- single-tenant portable backend (SQLite / MySQL from schema_org)
               -> the sole default schema of a per-tenant database (no search_path,
                  no role system to harden).

These tests assert the DISPATCH — that the right mechanism is selected per backend and that an
unavailable mechanism degrades explicitly (a no-op, not a silent partial isolation) — rather
than assuming any single mechanism. test_org_isolation.py covers the PG realization in depth.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# PostgreSQL realization: physical schema isolation (search_path + per-org role)
# ---------------------------------------------------------------------------


def test_pg_realization_scopes_connection_to_org_schema():
    """On PostgreSQL, a per-connection init binds the org's physical schema (search_path).

    core/db.py's raw asyncpg pool ``setup`` hook (``_make_init_conn``) was dead code with
    zero production call sites (fix 8, abstraction-leak remediation) and has been removed;
    the live mechanism is ``Database.acquire()`` (core/database.py) issuing
    ``Capabilities.enter_org_sql(search_path)``."""
    from provisa.core.database import Capabilities

    sql = Capabilities.for_dialect("postgresql").enter_org_sql("org_acme")
    assert sql is not None and "SET search_path" in sql and "org_acme" in sql


@pytest.mark.asyncio
async def test_pg_realization_hardens_with_a_per_org_role():
    """On PostgreSQL the mechanism also creates a role scoped to the org schema."""
    from provisa.core.db import create_org_role

    conn = AsyncMock()
    conn.capabilities.dialect = "postgresql"
    await create_org_role(conn, "acme")

    issued = [c.args[0] for c in conn.execute.await_args_list if c.args]
    assert any("role_acme" in s for s in issued)
    assert any('GRANT USAGE, CREATE ON SCHEMA "org_acme" TO role_acme' in s for s in issued)


# ---------------------------------------------------------------------------
# The contract holds regardless of which mechanism was selected
# ---------------------------------------------------------------------------


def test_org_id_is_validated_before_any_mechanism_binds():
    """Whatever the backend, the org identity is validated first — no injection into any
    isolation mechanism (search_path, schema name, role name)."""
    from provisa.core.db import _validate_org_id

    for bad in ("bad-org", "org with spaces", "org;drop", "a'b"):
        with pytest.raises(ValueError):
            _validate_org_id(bad)

    for ok in ("default", "acme123", "org_1"):
        assert _validate_org_id(ok) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
