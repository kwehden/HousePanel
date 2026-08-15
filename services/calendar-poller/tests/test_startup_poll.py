"""Calendar must poll on startup, not one interval later.

Without next_run_time the first poll waits a full CALENDAR_POLL_INTERVAL_SECONDS,
so the panel shows no calendar for 5 minutes after every restart. weather-poller
and sysmon-poller already polled immediately; calendar was the odd one out, and
nothing asserted the convention.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from calendar_poller import main as calendar_main


async def _enter_lifespan() -> MagicMock:
    """Run the lifespan with a stub client and scheduler; return the scheduler."""
    scheduler = MagicMock()
    with patch.object(calendar_main, "GoogleCalendarClient", MagicMock()), \
         patch.object(calendar_main, "AsyncIOScheduler", return_value=scheduler):
        app = MagicMock()
        app.state = MagicMock()
        async with calendar_main.lifespan(app):
            pass
    return scheduler


@pytest.mark.asyncio
async def test_first_poll_is_scheduled_immediately():
    scheduler = await _enter_lifespan()

    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs.get("next_run_time") is not None, \
        "calendar would not poll until a full interval had elapsed"


@pytest.mark.asyncio
async def test_recurring_interval_is_still_configured():
    scheduler = await _enter_lifespan()

    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["seconds"] == calendar_main.POLL_INTERVAL_SECONDS
    assert scheduler.add_job.call_args.args[1] == "interval"


@pytest.mark.asyncio
async def test_job_is_replaceable_so_restarts_do_not_duplicate_it():
    scheduler = await _enter_lifespan()

    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs.get("id")
    assert kwargs.get("replace_existing") is True


@pytest.mark.asyncio
async def test_scheduler_is_started_and_stopped():
    scheduler = await _enter_lifespan()

    scheduler.start.assert_called_once()
    scheduler.shutdown.assert_called_once()
