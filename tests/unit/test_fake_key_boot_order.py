# Copyright (c) 2026 Kenneth Stott
# Canary: 108d3865-ee06-4350-95d4-14011f55203c
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1494: the platform fake key is held before the engine is woken.

Waking a provisioned shard hands it the key (k8s_provisioner's fake-key Secret, built from
digest.platform_key()). cloud.provisa.dev's every start failed with FakeKeyMissing while the key
was loaded only near the end of startup, long after the wake; only a deployment that provisions
engines (GKE) wakes one at start, so no test start reached it."""

# Requirements: REQ-1494

from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "provisa" / "api" / "app.py"


def test_the_fake_key_is_loaded_once_after_the_control_planes_and_before_the_wake():
    source = _APP.read_text()
    load = "_set_fake_key(_fake_key.ensure(state.admin_db))"
    assert source.count(load) == 1
    at = source.index(load)
    assert source.index("await _init_control_planes(") < at  # the settings it reads are bound
    assert at < source.index("shard = await converge_boot_shard()")  # the wake hands it on
