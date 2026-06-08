from __future__ import annotations
import asyncio
import time as _time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from transport_adapter import state
from transport_adapter.routes import router
from shared.logging import make_logger, log_event

logger = make_logger("transport-adapter")
_PACIFIC = ZoneInfo("America/Los_Angeles")


async def _hourly_time_sync() -> None:
    while True:
        await asyncio.sleep(3600)
        if not state.giga_connected:
            continue
        now_pacific = datetime.now(_PACIFIC)
        utc_offset_min = int(now_pacific.utcoffset().total_seconds() / 60)
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
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="transport-adapter", lifespan=lifespan)
app.include_router(router)
