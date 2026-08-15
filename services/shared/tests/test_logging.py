"""Structured-log field merging.

Added after mutation testing: the `key not in (...stdlib attrs...)` filter and
the `and not key.startswith("_")` guard could both be flipped with the suite
green — dropping every caller-supplied field, or flooding each line with
LogRecord internals. Every alert and every incident trace in this repo is read
off these fields.
"""
from __future__ import annotations

import json
import logging

from shared.logging import log_event, make_logger


def _capture(logger) -> list[str]:
    lines: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    sink = _Sink()
    sink.setFormatter(logger.handlers[0].formatter)
    logger.handlers = [sink]
    return lines


def test_caller_fields_are_merged_into_the_json():
    logger = make_logger("test-svc")
    lines = _capture(logger)

    log_event(logger, "poll_success", provider="wttr_in", duration_ms=42)

    entry = json.loads(lines[-1])
    assert entry["event"] == "poll_success"
    assert entry["provider"] == "wttr_in"
    assert entry["duration_ms"] == 42


def test_core_envelope_is_always_present():
    logger = make_logger("test-svc")
    lines = _capture(logger)

    log_event(logger, "something")

    entry = json.loads(lines[-1])
    assert entry["service"] == "test-svc"
    assert entry["level"] == "INFO"
    assert entry["event"] == "something"
    assert entry["timestamp"].endswith("Z")


def test_logrecord_internals_are_not_leaked():
    """Flipping the exclusion filter would bury the real fields in noise."""
    logger = make_logger("test-svc")
    lines = _capture(logger)

    log_event(logger, "poll_success", provider="wttr_in")

    entry = json.loads(lines[-1])
    for internal in ("args", "levelno", "pathname", "funcName", "created",
                     "thread", "processName", "msecs", "relativeCreated"):
        assert internal not in entry, f"leaked LogRecord attribute {internal}"


def test_level_is_honoured():
    logger = make_logger("test-svc")
    lines = _capture(logger)

    log_event(logger, "poll_failed", level="warning", status=503)

    entry = json.loads(lines[-1])
    assert entry["level"] == "WARNING"
    assert entry["status"] == 503
