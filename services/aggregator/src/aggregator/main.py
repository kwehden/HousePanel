from __future__ import annotations
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .queue import TickerQueue
from .dedup import DedupCache
from .state import AggregatorState
from .drain import ticker_drain_loop
from .routes import router, init_singletons


@asynccontextmanager
async def lifespan(app: FastAPI):
    queue = TickerQueue()
    dedup = DedupCache()
    state = AggregatorState()
    init_singletons(queue, dedup, state)
    transport_url = os.environ.get("TRANSPORT_ADAPTER_URL", "http://housepanel-transport-adapter:8002")
    task = asyncio.create_task(ticker_drain_loop(queue, transport_url))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="HousePanel Aggregator", lifespan=lifespan)
app.include_router(router)
