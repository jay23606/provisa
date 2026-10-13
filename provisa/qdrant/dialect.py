# Copyright (c) 2026 Kenneth Stott
# Canary: b0425d52-02f9-4f0d-883d-73640917d4bb
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The ``qdrant`` SQLGlot dialect (REQ-2000): PostgreSQL text, the form the Qdrant driver reads a
governed statement in before lowering it to Qdrant's API. Defining the class registers the name."""

# Requirements: REQ-2000
from __future__ import annotations

from sqlglot.dialects.postgres import Postgres


class Qdrant(Postgres):
    """PostgreSQL, under the name a Qdrant source's statements are written for."""
