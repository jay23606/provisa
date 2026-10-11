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
# The core UI lane, after Playwright, whatever its outcome (lane.yml `after`).
#
#   ui-core-after.sh <playwright json report>
#
# 1. Names every test that did not execute (never counted as passed).
# 2. Leaves the Fabric capacity paused. The cloud-warehouse spec resumes it (a billable compute
#    unit) and pauses it in its own teardown -- which does not run when the spec dies or the job
#    is cut short. Its state is READ here: paused is done, Active is suspended, a transition is
#    waited out; only a capacity that does not end paused fails the step, and it says so.
# 3. Removes the credential files the prepare script wrote.
# Each step runs even when an earlier one failed; the script fails if any did.
set -euo pipefail
set +x

status=0

python3 "$(dirname "$0")/playwright_not_executed.py" "${1:?the Playwright JSON report}" || status=1

if [ -n "${FABRIC_RESOURCE_GROUP:-}" ] && [ -n "${FABRIC_CAPACITY_NAME:-}" ]; then
  ( cd "$GITHUB_WORKSPACE" && uv run python -c \
      "from tests.integration.fabric_capacity import ensure_capacity_paused as p; print('the Fabric capacity is', p())" ) \
    || { echo "::error::the Fabric capacity could not be confirmed paused: check it, it may be billing"; status=1; }
fi

rm -rf "${RUNNER_TEMP:?}/lane-credentials" || status=1

exit "$status"
