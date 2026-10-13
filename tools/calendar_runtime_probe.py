"""Exercise the packaged calendar lifespan, scheduler, server, TLS, and signer."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import logging
import os
from pathlib import Path
import ssl
from unittest.mock import patch

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google.oauth2 import service_account
import httpx
import uvicorn

import calendar_memory_probe as fixture


async def probe(args):
    os.environ["SSL_CERT_FILE"] = args.cert
    os.environ["REQUESTS_CA_BUNDLE"] = args.cert
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    upstream = await asyncio.start_server(fixture.respond, "127.0.0.1", 0, ssl=tls)
    downstream = await asyncio.start_server(fixture.respond, "127.0.0.1", 0)
    upstream_url = f"https://127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
    downstream_url = f"http://127.0.0.1:{downstream.sockets[0].getsockname()[1]}"
    credentials = service_account.Credentials.from_service_account_info({
        "type": "service_account", "client_email": "synthetic@example.invalid",
        "private_key_id": "synthetic", "token_uri": upstream_url + "/token",
        "private_key": Path(args.key).read_text(),
    }, scopes=fixture.calendar_module.SCOPES)
    fixture.calendar_module._CALENDAR_API_BASE = upstream_url + "/calendars"
    with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "one,two", "AGGREGATOR_URL": downstream_url}):
        import calendar_poller.main as module
    original_add_job = AsyncIOScheduler.add_job

    def fast_interval(self, *job_args, **kwargs):
        kwargs["seconds"] = 0.025
        return original_add_job(self, *job_args, **kwargs)

    server = uvicorn.Server(uvicorn.Config(module.app, host="127.0.0.1", port=0,
        access_log=False, log_config=None))
    with patch.object(fixture.calendar_module.google.auth, "default", return_value=(credentials, "test")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "one,two"}), \
         patch.object(AsyncIOScheduler, "add_job", fast_interval):
        async with upstream, downstream, httpx.AsyncClient(timeout=5) as scrape:
            task = asyncio.create_task(server.serve())
            try:
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Calendar server failed to start")
                    await asyncio.sleep(0.01)
                runner = module.app.state.poll_runner
                for cell in runner._poll.__closure__:
                    value = cell.cell_contents
                    if isinstance(value, fixture.calendar_module.GoogleCalendarClient):
                        value._http_client._transport._pool._keepalive_expiry = 0
                    elif isinstance(value, httpx.AsyncClient):
                        value._transport._pool._keepalive_expiry = 0
                url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
                next_sample = args.warmup
                next_refresh = 12
                while fixture.metrics.poll_success_total < args.cycles:
                    await asyncio.sleep(0.01)
                    cycle = fixture.metrics.poll_success_total
                    if fixture.metrics.poll_failure_total or fixture.metrics.push_failure_total:
                        raise RuntimeError("Synthetic runtime polling or delivery failed")
                    if cycle >= next_refresh:
                        credentials.token = None
                        next_refresh = cycle + 12
                    if cycle >= next_sample:
                        fixture.sample(cycle, "running")
                        for path in ("/metrics", "/healthz"):
                            response = await scrape.get(url + path)
                            response.raise_for_status()
                        next_sample = cycle + args.sample_every
                fixture.sample(fixture.metrics.poll_success_total, "running")
                server.should_exit = True
                await task
                assert fixture.metrics.poll_success_total == fixture.metrics.push_success_total
                assert fixture.metrics.poll_failure_total == 0
                assert fixture.metrics.push_failure_total == 0
            finally:
                server.should_exit = True
                if not task.done():
                    await task
    gc.collect()
    fixture.sample(fixture.metrics.poll_success_total, "closed")
    ctypes.CDLL(None).malloc_trim(0)
    fixture.sample(fixture.metrics.poll_success_total, "after_malloc_trim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3000)
    parser.add_argument("--warmup", type=int, default=12)
    parser.add_argument("--sample-every", type=int, default=250)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    if not 1 <= args.warmup <= args.cycles or args.sample_every < 1:
        parser.error("warmup must be within cycles; sample-every must be positive")
    logging.disable(logging.CRITICAL)
    asyncio.run(probe(args))
