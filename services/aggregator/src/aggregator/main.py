from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from fastapi import FastAPI
from shared.body_limit import BodyLimitMiddleware
from .queue import TickerQueue
from .dedup import DedupCache
from .state import AggregatorState
from .drain import ticker_drain_loop
from .dispatch_worker import create_worker
from .transport_client import init_dispatch_worker
from .routes import router, init_singletons


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    queue = TickerQueue()
    dedup = DedupCache()
    state = AggregatorState()
    init_singletons(queue, dedup, state)
    worker = create_worker()
    init_dispatch_worker(worker)
    drain_task = asyncio.create_task(ticker_drain_loop(queue))
    worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        drain_task.cancel()
        worker_task.cancel()
        await asyncio.gather(drain_task, worker_task, return_exceptions=True)


app = FastAPI(title="HousePanel Aggregator", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)
app.include_router(router)
