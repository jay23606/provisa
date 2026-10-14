# Copyright (c) 2026 Kenneth Stott
# Canary: 9c2f4a81-3d67-4e15-8b0a-2a6e3c7f41d9
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""REQ-1149: the `signal` change_signal — a data-less external refresh trigger.

Covers the signal vocabulary (push-timed, poll-style re-pull, not CDC) and the refresh policy a
signal arms. The receiver -- the webhook, which asks for the builds -- is
test_signal_webhook.py's.
"""

from __future__ import annotations


from provisa.core import change_signal as cs


# ------------------------------------------------------- vocabulary


def test_signal_is_valid_and_a_trigger():
    assert "signal" in cs.VALID_SIGNALS
    assert cs.is_trigger("signal")
    assert not cs.is_push("signal")  # not a CDC carrier
    assert not cs.is_poll("signal")


def test_signal_landing_is_poll_style_not_cdc():
    # a signal carries no rows: it re-pulls (replace / watermark-append), never CDC upserts
    assert cs.select_landing_shape("signal", watermark_column=None) == cs.REPLACE
    assert cs.select_landing_shape("signal", watermark_column="ts") == cs.APPEND


def test_signal_provider_is_a_receiver():
    assert cs.to_provider("signal", "mongodb") == "signal"


def test_signal_has_no_poll_freshness_mode():
    assert cs.to_freshness_mode("signal") is None


def test_signal_is_probe_capable_in_policy():
    # a signal source arms the probe gate so the REQ-1141 scheduler runs its trigger-token check
    from types import SimpleNamespace

    from provisa.federation.scheduled_refresh import resolve_refresh_policy

    source = SimpleNamespace(
        load_protected=True,
        off_peak_window=None,
        off_peak_tz="UTC",
        cache_ttl=None,
        change_signal="signal",
    )
    table = SimpleNamespace(
        load_protected=None,
        off_peak_window=None,
        off_peak_tz=None,
        cache_ttl=None,
        change_signal=None,
        live=None,
    )
    policy = resolve_refresh_policy(source, table)
    assert policy.probe_capable
    assert policy.armed
