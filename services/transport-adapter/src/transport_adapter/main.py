from __future__ import annotations
import asyncio
import time as _time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from shared.body_limit import BodyLimitMiddleware
from transport_adapter import state
from transport_adapter.routes import router
from transport_adapter.state_refresh import close_poller_refresh
from shared.logging import make_logger, log_event

logger = make_logger("transport-adapter")
_PACIFIC = ZoneInfo("America/Los_Angeles")


async def _hourly_time_sync() -> None:
    while True:
        await asyncio.sleep(3600)
        if not state.giga_connected:
            continue
        now_pacific = datetime.now(_PACIFIC)
        offset = now_pacific.utcoffset()
        assert offset is not None
        utc_offset_min = int(offset.total_seconds() / 60)
        try:
            state.normal_queue.put_nowait({
                "cmd": "TIME",
                "epoch": int(_time.time()),
                "utc_offset_min": utc_offset_min,
            })
            log_event(logger, "periodic_time_sync", utc_offset_min=utc_offset_min)
        except asyncio.QueueFull:
            log_event(logger, "periodic_time_sync_queue_full", level="warning")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    task = asyncio.create_task(_hourly_time_sync())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await close_poller_refresh()


app = FastAPI(title="transport-adapter", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)
app.include_router(router)
