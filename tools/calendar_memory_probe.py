#!/usr/bin/env python3
"""Profile calendar polling with synthetic calendars and local OAuth/HTTP.

Run inside the calendar image. No Google credentials or cluster writes are used.
Pass --cert/--key for local TLS and --trace for Python allocation attribution.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import logging
import os
from pathlib import Path
import ssl
import tracemalloc
from unittest.mock import patch

from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
import httpx

import calendar_poller.calendar_client as calendar_module
from calendar_poller.poller import CalendarPollerState, poll_google_calendar, metrics
from shared.polling import PollRunner


async def respond(reader, writer):
    try:
        while True:
            header = await reader.readuntil(b"\r\n\r\n")
            request_line = header.split(b"\r\n", 1)[0]
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    await reader.readexactly(int(line.split(b":", 1)[1]))
            if b"/token " in request_line:
                payload = {"access_token": "synthetic", "expires_in": 3600, "token_type": "Bearer"}
            elif b"/calendars/" in request_line:
                payload = {"items": [{
                    "id": f"event-{i}", "summary": f"Synthetic appointment {i}",
                    "start": {"dateTime": "2026-10-06T10:00:00-07:00"},
                    "end": {"dateTime": "2026-10-06T11:00:00-07:00"},
                } for i in range(26)]}
            else:
                payload = {"accepted": True}
            body = json.dumps(payload).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


def sample(cycle, stage):
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    result = {"cycle": cycle, "stage": stage,
              "rss_kib": int(status["VmRSS"].split()[0]),
              "fds": len(list(Path("/proc/self/fd").iterdir())),
              "threads": int(status["Threads"]),
              "tasks": len(asyncio.all_tasks())}
    if tracemalloc.is_tracing():
        result["python_live_kib"] = round(tracemalloc.get_traced_memory()[0] / 1024, 1)
    print(json.dumps(result), flush=True)


async def probe(args):
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    tls = None
    scheme = "http"
    if args.cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.cert, args.key)
        os.environ["SSL_CERT_FILE"] = args.cert
        os.environ["REQUESTS_CA_BUNDLE"] = args.cert
        scheme = "https"
    upstream = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=tls)
    downstream = await asyncio.start_server(respond, "127.0.0.1", 0)
    upstream_url = f"{scheme}://127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
    downstream_url = f"http://127.0.0.1:{downstream.sockets[0].getsockname()[1]}"
    if args.credentials == "service-account":
        credentials = service_account.Credentials.from_service_account_info({
            "type": "service_account", "client_email": "synthetic@example.invalid",
            "private_key_id": "synthetic", "private_key": Path(args.key).read_text(),
            "token_uri": f"{upstream_url}/token",
        }, scopes=calendar_module.SCOPES)
    else:
        credentials = Credentials(
            token="synthetic", refresh_token="synthetic", token_uri=f"{upstream_url}/token",
            client_id="synthetic", client_secret="synthetic",
        )
    calendar_module._CALENDAR_API_BASE = f"{upstream_url}/calendars"
    with patch.object(calendar_module.google.auth, "default", return_value=(credentials, "test")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "one,two"}):
        client = calendar_module.GoogleCalendarClient()
    state = CalendarPollerState()
    logger = logging.getLogger("probe")
    async with upstream, downstream, httpx.AsyncClient(timeout=5) as http:
        runner = PollRunner(lambda: poll_google_calendar(client, state, downstream_url, logger, http), logger)
        baseline = None
        if args.trace:
            tracemalloc.start(10)
        try:
            for cycle in range(1, args.cycles + 1):
                if args.refresh_every and cycle % args.refresh_every == 0:
                    credentials.token = None
                if args.expire_connections:
                    # Model five minutes between polls without waiting five minutes.
                    client._http_client._transport._pool._keepalive_expiry = 0
                    http._transport._pool._keepalive_expiry = 0
                if args.mode == "auth":
                    credentials.token = None
                    await asyncio.to_thread(client._ensure_valid_token)
                else:
                    await runner.run()
                if cycle == args.warmup:
                    if args.collect_gc:
                        gc.collect()
                    sample(cycle, "baseline")
                    if args.trace:
                        baseline = tracemalloc.take_snapshot()
                elif cycle % args.sample_every == 0:
                    sample(cycle, "running")
                    if args.collect_gc:
                        gc.collect()
                        sample(cycle, "after_gc")
            if args.trace and baseline:
                snapshot = tracemalloc.take_snapshot()
                for stat in snapshot.compare_to(baseline, "lineno")[:15]:
                    print(str(stat), flush=True)
            if args.mode == "poll":
                assert metrics.poll_success_total == args.cycles
                assert metrics.push_success_total == args.cycles
        finally:
            await runner.close()
            client.close()
    await asyncio.sleep(0.01)
    gc.collect()
    sample(args.cycles, "closed")
    # Diagnostic only: distinguish free native allocator pages from live objects.
    ctypes.CDLL(None).malloc_trim(0)
    sample(args.cycles, "after_malloc_trim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=12)
    parser.add_argument("--sample-every", type=int, default=250)
    parser.add_argument("--refresh-every", type=int, default=12)
    parser.add_argument("--expire-connections", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--collect-gc", action="store_true", help="Diagnostic only; CI measures without forced GC")
    parser.add_argument("--credentials", choices=("service-account", "user-oauth"), default="service-account")
    parser.add_argument("--mode", choices=("poll", "auth"), default="poll")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--native-output")
    args = parser.parse_args()
    if args.cycles < 1 or not 1 <= args.warmup <= args.cycles or args.sample_every < 1:
        parser.error("cycles and sample-every must be positive; warmup must be within the run")
    if args.refresh_every < 0:
        parser.error("refresh-every must be nonnegative (0 disables forced refresh)")
    if bool(args.cert) != bool(args.key):
        parser.error("cert and key must be supplied together")
    if args.credentials == "service-account" and not args.key:
        parser.error("service-account mode requires a synthetic RSA --key (use --credentials user-oauth for HTTP-only probes)")
    logging.disable(logging.CRITICAL)
    if args.native_output:
        import memray
        with memray.Tracker(args.native_output, native_traces=True):
            asyncio.run(probe(args))
    else:
        asyncio.run(probe(args))
