from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from shared.logging import log_event
from shared.models import CalendarEvent

from calendar_poller.calendar_client import CalendarAPIError, GoogleCalendarClient


@dataclass
class CalendarPollerState:
    last_events: list[CalendarEvent] = field(default_factory=list)
    last_poll_timestamp: datetime | None = None
    last_poll_event_count: int = 0


async def push_calendar_update(
    events: list[CalendarEvent],
    aggregator_url: str,
    logger: logging.Logger,
) -> None:
    body = {
        "source": "calendar-poller",
        "event_type": "calendar-update",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "priority": 10,
        "payload": {"events": [dataclasses.asdict(e) for e in events]},
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{aggregator_url}/internal/events", json=body)
            resp.raise_for_status()
    except Exception as exc:
        log_event(logger, "push_calendar_update_error", level="error", error=str(exc))


async def poll_google_calendar(
    client: GoogleCalendarClient,
    state: CalendarPollerState,
    aggregator_url: str,
    logger: logging.Logger,
) -> None:
    log_event(logger, "poll_started")
    now = datetime.now(timezone.utc)
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lookahead = int(os.getenv("CALENDAR_LOOKAHEAD_DAYS", "30"))
    time_max = time_min + timedelta(days=lookahead)
    start_mono = time.monotonic()
    try:
        events = await asyncio.to_thread(client.fetch_events, time_min, time_max)
    except CalendarAPIError as exc:
        log_event(
            logger,
            "poll_error",
            level="error",
            http_status_code=exc.http_status,
            error_message=exc.message,
        )
        return
    duration_ms = int((time.monotonic() - start_mono) * 1000)
    state.last_events = events
    state.last_poll_timestamp = datetime.now(timezone.utc)
    state.last_poll_event_count = len(events)
    await push_calendar_update(events, aggregator_url, logger)
    log_event(
        logger,
        "poll_success",
        event_count=len(events),
        poll_duration_ms=duration_ms,
    )
