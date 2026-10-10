#!/usr/bin/env python3
"""Exercise sysmon polling against loopback HTTP without upstream credentials.

Run in a sysmon image with this file mounted, or with the service installed.
Supports the previous no-argument _poll to compare old images with the fix.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import inspect
import json
import logging
from pathlib import Path

import httpx
import sysmon_poller.main as sysmon


def sample(cycles: int) -> None:
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    print(json.dumps({
        "cycles": cycles,
        "rss_kib": int(status["VmRSS"].split()[0]),
        "fds": len(list(Path("/proc/self/fd").iterdir())),
        "tasks": len(asyncio.all_tasks()),
        "threads": int(status["Threads"]),
    }), flush=True)


async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            header = await reader.readuntil(b"\r\n\r\n")
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    await reader.readexactly(int(line.split(b":", 1)[1]))
            body = b'{"t":25,"h":30}'
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def probe(cycles: int, sample_every: int, delay: float) -> None:
    sensor = await asyncio.start_server(respond, "127.0.0.1", 0)
    aggregator = await asyncio.start_server(respond, "127.0.0.1", 0)
    sysmon._ARDTEMP_URL = f"http://127.0.0.1:{sensor.sockets[0].getsockname()[1]}"
    sysmon._AGGREGATOR_URL = f"http://127.0.0.1:{aggregator.sockets[0].getsockname()[1]}"
    injected_client = "client" in inspect.signature(sysmon._poll).parameters
    async with sensor, aggregator, httpx.AsyncClient(timeout=5.0) as client:
        for i in range(1, cycles + 1):
            poll = sysmon._poll(client) if injected_client else sysmon._poll()
            await asyncio.create_task(poll)
            if delay:
                await asyncio.sleep(delay)
            if i % sample_every == 0 or i == cycles:
                sample(i)
        assert sysmon.metrics.poll_success_total == cycles
        assert sysmon.metrics.push_success_total == cycles
    gc.collect()
    await asyncio.sleep(0.01)
    sample(cycles)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3000)
    parser.add_argument("--sample-every", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0)
    args = parser.parse_args()
    if args.cycles < 1 or args.sample_every < 1 or args.delay < 0:
        parser.error("cycles/sample-every must be positive; delay must be nonnegative")
    logging.disable(logging.CRITICAL)
    asyncio.run(probe(args.cycles, args.sample_every, args.delay))
