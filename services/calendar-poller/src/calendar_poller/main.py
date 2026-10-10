from __future__ import annotations

import os
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import Response
import httpx

from shared.logging import make_logger
from shared.metrics import CONTENT_TYPE, render
from shared.polling import PollRunner

from calendar_poller.calendar_client import GoogleCalendarClient
from calendar_poller.poller import CalendarPollerState, metrics as source_metrics, poll_google_calendar

AGGREGATOR_URL = os.getenv("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
POLL_INTERVAL_SECONDS = int(os.getenv("CALENDAR_POLL_INTERVAL_SECONDS", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logger = make_logger("calendar-poller")
logger.setLevel(LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    with closing(GoogleCalendarClient()) as calendar_client:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            source_metrics.poll_interval_seconds = POLL_INTERVAL_SECONDS
            state = CalendarPollerState()
            runner = PollRunner(
                lambda: poll_google_calendar(
                    calendar_client, state, AGGREGATOR_URL, logger, http_client
                ), logger,
            )
            scheduler = AsyncIOScheduler()
            scheduler.add_job(
                runner.run,
                "interval",
                seconds=POLL_INTERVAL_SECONDS,
                id="poll_calendar",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )
            app.state.poller_state = state
            app.state.poll_runner = runner
            scheduler.start()
            try:
                yield
            finally:
                scheduler.shutdown(wait=False)
                await runner.close()


app = FastAPI(lifespan=lifespan)


@app.post("/internal/poll-now", status_code=202)
async def poll_now() -> dict[str, bool]:
    app.state.poll_runner.request()
    return {"accepted": True}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=render(source_metrics.render()), media_type=CONTENT_TYPE)


@app.get("/healthz")
async def healthz() -> dict[str, str | int | None]:
    state: CalendarPollerState = app.state.poller_state
    return {
        "status": "ok",
        "last_poll_timestamp": (
            state.last_poll_timestamp.isoformat()
            if state.last_poll_timestamp is not None
            else None
        ),
        "last_poll_event_count": state.last_poll_event_count,
    }
