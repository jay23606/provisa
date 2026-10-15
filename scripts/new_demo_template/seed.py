# Copyright (c) 2026 Kenneth Stott
# Canary: bb1f1e53-ee38-481d-bb43-cd21d341b3de
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
#
"""The __NAME__ demo's seeder: the `seeder` service runs it once after the database is healthy.
TODO: write what the demo's data needs beyond db/init.sql. A marker on the data directory makes a
restart with kept data write nothing."""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = Path("/data-marker/.seeded")


def main() -> int:
    if MARKER.exists():
        print(f"__NAME__ demo already seeded ({MARKER.read_text().strip()}); skipping")
        return 0
    MARKER.write_text("seeded\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
