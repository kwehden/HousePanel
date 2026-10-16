"""Reproduce CPython 3.12 datetime cache retention in a fresh process.

Diagnostic only: this does not import Calendar, access credentials, or attach to
another process. Run in the deployed image, with and without --retain-control.
See CPython v3.12.13 Objects/typeobject.c and Modules/_datetimemodule.c:
temporary timezone method names can remain in the bounded type lookup cache.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import gc
import json
import sys
import tracemalloc
from zoneinfo import ZoneInfo


def timestamp(value: datetime) -> float:
    return value.timestamp()


def payload(value: datetime) -> str:
    return value.isoformat()


def probe(iterations: int, retain_control: bool = False) -> dict:
    if iterations < 10:
        raise ValueError("iterations must be at least 10")
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use the deployed CPython 3.12 image for this reproducer")
    if tracemalloc.is_tracing():
        raise RuntimeError("Run in a fresh process without an existing tracer")
    operation = payload if retain_control else timestamp
    allocation_line = operation.__code__.co_firstlineno + 1
    value = datetime.now(ZoneInfo("Etc/UTC"))
    retained = []
    checkpoints = sorted({iterations // 100, iterations // 10, iterations} - {0})
    samples = []

    def measure(cycle: int, stage: str) -> dict:
        gc.collect()
        snapshot = tracemalloc.take_snapshot()
        stats = [s for s in snapshot.statistics("lineno")
                 if s.traceback[0].filename == __file__
                 and s.traceback[0].lineno == allocation_line]
        return {"cycle": cycle, "stage": stage,
                "allocation_bytes": sum(s.size for s in stats),
                "allocation_count": sum(s.count for s in stats)}

    gc.collect()
    sys._clear_type_cache()
    tracemalloc.start(1)
    try:
        for cycle in range(1, iterations + 1):
            result = operation(value)
            if retain_control:
                retained.append(result)
            del result
            if cycle in checkpoints:
                samples.append(measure(cycle, "after_gc"))
        sys._clear_type_cache()
        samples.append(measure(iterations, "after_type_cache_clear"))
        # Keep the positive-control objects alive through every measurement.
        assert len(retained) == (iterations if retain_control else 0)
        return {"python": sys.version, "retain_control": retain_control,
                "iterations": iterations, "samples": samples}
    finally:
        tracemalloc.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100000)
    parser.add_argument("--retain-control", action="store_true")
    args = parser.parse_args()
    try:
        report = probe(args.iterations, args.retain_control)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
