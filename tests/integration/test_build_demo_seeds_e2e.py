# Copyright (c) 2026 Kenneth Stott
# Canary: 2b08e6ca-e038-454c-9895-618a4591b962
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""E2E: the release build's demo seeding (scripts/build_demo_seeds.py, REQ-2006).

The ``test`` instance: the script, run as the release runs it, on a named-demo directory of this
test's own -- one published demo over a SQLite file, which has no data stores to bring up -- starts
its own embedded control plane and a sandbox tier in seeding mode, and writes the demo's seed
beside its demo.yaml; an unpublished demo gets none."""

# Requirements: REQ-2006

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.test_demo_sandboxes_e2e import _demo

pytestmark = [pytest.mark.integration, pytest.mark.local_platform]

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_demo_seeds.py"


def test_the_release_seeding_writes_each_published_demos_seed(tmp_path):
    named = tmp_path / "named"
    _demo(named, "alpha", published=True)
    _demo(named, "gamma", published=False)
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), "--named-dir", str(named), "--timeout", "300"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, (done.stdout[-4000:], done.stderr[-8000:])
    record = json.loads((named / "alpha" / "seeded" / "replicas.json").read_text())
    assert [r["table_name"] for r in record["replicas"]] == ["animals"]
    assert (named / "alpha" / "seeded" / "replicas.duckdb").is_file()
    assert not (named / "gamma" / "seeded").exists()
