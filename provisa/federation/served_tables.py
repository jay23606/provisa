# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The tables a source's bundled pgwire server serves, for a type whose server serves only the
tables registered from the source (REQ-1954). Read by the server's model (``pgwire_replica``,
``servicenow``) and the Trino catalog; set from the model on every schema build
(``api/app_rebuild.serve_registered_tables``)."""

# Requirements: REQ-1954

from __future__ import annotations

from collections.abc import Iterable

#: Source id -> the tables registered from it that its server serves, for a type whose server
#: serves only those (``SERVES_REGISTERED_TABLES``). Set from the model on every schema build.
_SERVED_TABLES: dict[str, tuple[str, ...]] = {}
#: Types whose server is given the tables registered from the source and serves only those
#: (REQ-1954): a ServiceNow server resolves every table it serves before it listens, and an
#: instance has thousands.
SERVES_REGISTERED_TABLES = frozenset({"servicenow"})


def served_tables(source_id: str) -> tuple[str, ...]:
    """The registered tables ``source_id``'s server serves, by name, in order."""
    return _SERVED_TABLES.get(source_id, ())


def serve_tables(source_id: str, names: Iterable[str]) -> bool:
    """Record the tables registered from ``source_id``; True when they differ from the ones its
    server was last given (none, before the first record), so a server already running must be
    started again to serve them."""
    wanted = tuple(sorted(set(names)))
    before = _SERVED_TABLES.get(source_id, ())
    _SERVED_TABLES[source_id] = wanted
    return before != wanted
