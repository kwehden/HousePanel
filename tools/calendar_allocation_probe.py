"""Profile a dedicated read-only calendar canary; never send updates to the panel.

Run in a separate pod with the deployed image and read-only calendar credentials.
Logs contain allocation counts and source locations, not event data or tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import json
import logging
import os
from pathlib import Path
import tracemalloc

import uvicorn


class MallInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in (
        "arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks",
        "fsmblks", "uordblks", "fordblks", "keepcost")]


def sample(cycle, stage, libc):
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    memory = dict(line.split(":", 1) for line in Path("/proc/self/smaps_rollup").read_text().splitlines()[1:])
    native = libc.mallinfo2()
    record = {"cycle": cycle, "stage": stage,
        "rss_kib": int(status["VmRSS"].split()[0]),
        "anonymous_kib": int(memory["Anonymous"].split()[0]),
        "fds": len(list(Path("/proc/self/fd").iterdir())),
        "threads": int(status["Threads"]), "tasks": len(asyncio.all_tasks()),
        "native_used_kib": native.uordblks / 1024,
        "native_free_kib": native.fordblks / 1024,
        "native_arena_kib": native.arena / 1024,
        "native_mmap_kib": native.hblkhd / 1024, "gc_counts": gc.get_count()}
    if tracemalloc.is_tracing():
        record["python_live_kib"] = tracemalloc.get_traced_memory()[0] / 1024
        record["tracer_metadata_kib"] = tracemalloc.get_tracemalloc_memory() / 1024
    print(json.dumps(record), flush=True)


async def discard(reader, writer):
    try:
        while True:
            headers = await reader.readuntil(b"\r\n\r\n")
            for line in headers.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    await reader.readexactly(int(line.split(b":", 1)[1]))
            body = b'{"accepted":true}'
            writer.write(b"HTTP/1.1 202 Accepted\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def profile(args):
    # Override delivery before importing app configuration, even if its
    # environment points at a real production aggregator.
    os.environ["AGGREGATOR_URL"] = "http://127.0.0.1:18001"
    os.environ["CALENDAR_POLL_INTERVAL_SECONDS"] = str(args.interval)
    logging.disable(logging.CRITICAL)
    if args.trace:
        tracemalloc.start(5)
    import calendar_poller.main as module
    from calendar_poller.poller import metrics

    libc = ctypes.CDLL(None)
    libc.mallinfo2.restype = MallInfo
    baseline = None
    async with await asyncio.start_server(discard, "127.0.0.1", 18001):
        server = uvicorn.Server(uvicorn.Config(module.app, host="127.0.0.1", port=18003,
            access_log=False, log_config=None))
        task = asyncio.create_task(server.serve())
        try:
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Canary failed to start")
                await asyncio.sleep(0.05)
            runner = module.app.state.poll_runner
            client = next(cell.cell_contents for cell in runner._poll.__closure__
                if hasattr(cell.cell_contents, "_credentials"))
            client._http_client._transport._pool._keepalive_expiry = 0
            next_sample = 12
            next_refresh = 12
            while metrics.poll_success_total < args.cycles:
                await asyncio.sleep(0.1)
                cycle = metrics.poll_success_total
                if metrics.poll_failure_total > 5:
                    raise RuntimeError("Read-only upstream poll failures")
                if cycle >= next_refresh:
                    client._credentials.token = None
                    next_refresh = cycle + 12
                if cycle >= next_sample:
                    sample(cycle, "running", libc)
                    if args.trace and baseline is None:
                        baseline = tracemalloc.take_snapshot()
                    next_sample = cycle + 12
            await runner.close()
            sample(cycle, "before_gc", libc)
            gc.collect()
            sample(cycle, "after_gc", libc)
            if baseline:
                endpoint = tracemalloc.take_snapshot()
                statistics = endpoint.compare_to(baseline, "lineno")[:15]
                del endpoint
                for stat in statistics:
                    print(json.dumps({"allocation": str(stat)}), flush=True)
                del statistics
            libc.malloc_trim(0)
            sample(cycle, "after_trim", libc)
            print(json.dumps({"success_polls": metrics.poll_success_total,
                "failed_polls": metrics.poll_failure_total,
                "success_pushes": metrics.push_success_total,
                "failed_pushes": metrics.push_failure_total}), flush=True)
        finally:
            server.should_exit = True
            await task
        gc.collect()
        sample(metrics.poll_success_total, "closed", libc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-upstream", action="store_true")
    parser.add_argument("--cycles", type=int, default=600)
    parser.add_argument("--interval", type=int, default=2)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    if not args.allow_real_upstream:
        parser.error("Use --allow-real-upstream only in a dedicated read-only canary")
    if args.cycles < 12 or args.interval < 1:
        parser.error("cycles must be at least 12 and interval must be positive")
    asyncio.run(profile(args))
