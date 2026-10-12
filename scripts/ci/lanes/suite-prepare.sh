#!/usr/bin/env bash
# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
#
# A container-suite lane, before it runs (lane.yml `prepare`): how many stacks this runner holds.
set -euo pipefail

uv run python -c "from tests.itest_stack import concurrent_session_limit as n; \
  print('docker stack slots on this runner:', n()); assert n() >= 1"

# REQ-1992: tests/integration/test_org_folder_crypt.py mounts an org's encrypted folder with
# gocryptfs over FUSE, as a node does.
sudo apt-get update -qq
sudo apt-get install -y -qq gocryptfs fuse3
