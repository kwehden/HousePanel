from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from shared.logging import make_logger

from calendar_poller.calendar_client import GoogleCalendarClient
from calendar_poller.poller import CalendarPollerState, poll_google_calendar

AGGREGATOR_URL = os.getenv("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
POLL_INTERVAL_SECONDS = int(os.getenv("CALENDAR_POLL_INTERVAL_SECONDS", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logger = make_logger("calendar-poller")
logger.setLevel(LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    calendar_client = GoogleCalendarClient()
    state = CalendarPollerState()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_google_calendar,
        "interval",
        seconds=POLL_INTERVAL_SECONDS,
        args=[calendar_client, state, AGGREGATOR_URL, logger],
    )
    scheduler.start()
    app.state.poller_state = state
    app.state.poll_args = (calendar_client, state, AGGREGATOR_URL, logger)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


@app.post("/internal/poll-now", status_code=202)
async def poll_now() -> dict:
    client, poller_state, aggregator_url, _logger = app.state.poll_args
    asyncio.create_task(poll_google_calendar(client, poller_state, aggregator_url, _logger))
    return {"accepted": True}


@app.get("/healthz")
async def healthz() -> dict:
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
