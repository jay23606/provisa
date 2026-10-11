# Copyright (c) 2026 Kenneth Stott
# Canary: 196ae8b1-7e8c-4502-ae03-ba1eb5896bda
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A collector that cannot be reached is said once, in one line, and once more when it is back.

The metric export thread logged a traceback on every tick it could not export. One of those
was the exporter library's own: after a failed attempt it waits out its backoff and sends
again with whatever time is left; a late wake-up leaves none, and the HTTP client refuses a
timeout of zero or less with a ValueError the library does not count as a failed send
("Attempted to set connect timeout to -0.5677816867828369", a maintainer's server log)."""

from __future__ import annotations

import logging

import pytest
import requests
from opentelemetry.exporter.otlp.proto.http import metric_exporter as lib
from opentelemetry.sdk.metrics import MeterProvider

from provisa.api.otel_setup import _MetricExports

ENDPOINT = "http://collector.invalid:4318"
_OURS = "provisa.api.otel_setup"


class _Reply:
    ok = True
    status_code = 200
    reason = "OK"


class _Collector:
    """A stand-in for the exporter's HTTP session: refuses the connection until ``up``, and
    refuses a timeout of zero or less exactly as urllib3 does."""

    def __init__(self) -> None:
        self.up = False
        self.timeouts: list[float] = []

    def post(self, timeout=None, **_request):
        self.timeouts.append(timeout)
        if timeout <= 0:
            raise ValueError(
                f"Attempted to set connect timeout to {timeout}, but the timeout cannot be set "
                "to a value less than or equal to 0."
            )
        if not self.up:
            raise requests.exceptions.ConnectionError("connection refused")
        return _Reply()


@pytest.fixture
def export(monkeypatch):
    """The process's metric export, its collector, and a clock the backoff wait moves."""
    exporter = lib.OTLPMetricExporter(endpoint=ENDPOINT + "/v1/metrics", timeout=1)
    collector = _Collector()
    monkeypatch.setattr(exporter._session, "post", collector.post)
    clock = [1000.0]
    monkeypatch.setattr(lib, "time", lambda: clock[0])
    monkeypatch.setattr(lib.random, "uniform", lambda _low, _high: 1.0)  # a 1 s first backoff

    def _late_wake(seconds: float) -> bool:
        # The wait returns half a second late: the export's one-second deadline has passed.
        clock[0] += seconds + 0.5677816867828369
        return False

    monkeypatch.setattr(exporter._shutdown_in_progress, "wait", _late_wake)
    exports = _MetricExports(exporter, interval_millis=3_600_000)  # the thread never ticks here
    provider = MeterProvider(metric_readers=[exports.reader])
    counter = provider.get_meter("test").create_counter("requests")
    exports.start(exporter, ENDPOINT)
    try:
        yield exports, collector, counter
    finally:
        exports.stop()


def _ours(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _OURS and r.levelno >= logging.WARNING]


def test_the_library_sends_again_with_no_time_left(export):
    """The condition itself, shown on the installed library: the second attempt is made with a
    negative timeout, which is what raises out of the export."""
    exports, collector, counter = export
    counter.add(1)
    with pytest.raises(ValueError, match="connect timeout"):
        exports.reader.collect()
    # The first attempt has the whole second (the library sends it twice at once on a refused
    # connection); the attempt after the backoff is sent with less than none.
    assert collector.timeouts[0] == pytest.approx(1.0)
    assert collector.timeouts[-1] == pytest.approx(-0.5677816867828369)


def test_an_export_that_cannot_be_sent_is_one_line_naming_the_endpoint(export, caplog):
    exports, _collector, counter = export
    caplog.set_level(logging.DEBUG)
    counter.add(1)
    exports.collect_once()
    (line,) = _ours(caplog)
    assert line.getMessage().startswith(f"OTel metrics are not reaching {ENDPOINT}: ValueError: ")
    assert "connect timeout" in line.getMessage()
    assert line.exc_info is None, "a traceback every tick is what this replaces"


def test_it_is_said_once_until_the_collector_is_back_and_then_once_more(export, caplog):
    exports, collector, counter = export
    caplog.set_level(logging.WARNING)
    for _tick in range(3):
        counter.add(1)
        exports.collect_once()
    assert len(_ours(caplog)) == 1, [r.getMessage() for r in _ours(caplog)]

    collector.up = True
    counter.add(1)
    exports.collect_once()
    lines = [r.getMessage() for r in _ours(caplog)]
    assert lines[1] == f"OTel metrics are reaching {ENDPOINT} again (3 export(s) did not)"

    counter.add(1)
    exports.collect_once()
    assert len(_ours(caplog)) == 2, "an export that succeeds says nothing"


def test_an_export_the_exporter_reports_failed_is_the_same_condition(export, caplog, monkeypatch):
    """Not every failure raises: a refused connection with no time left to retry comes back as
    the exporter's failure result."""
    exports, collector, counter = export
    caplog.set_level(logging.WARNING)
    # No late wake-up here: the library sees its backoff does not fit and gives up by itself.
    monkeypatch.setattr(lib.random, "uniform", lambda _low, _high: 1.2)
    counter.add(1)
    exports.collect_once()
    (line,) = _ours(caplog)
    assert line.getMessage() == (
        f"OTel metrics are not reaching {ENDPOINT}: the exporter reported a failed export"
    )
    assert all(t > 0 for t in collector.timeouts)
