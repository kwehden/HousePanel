"""Calendar must poll on startup, not one interval later.

Without next_run_time the first poll waits a full CALENDAR_POLL_INTERVAL_SECONDS,
so the panel shows no calendar for 5 minutes after every restart. weather-poller
and sysmon-poller already polled immediately; calendar was the odd one out, and
nothing asserted the convention.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_manual_refreshes_coalesce_and_clients_close_after_poll():
    started, release = asyncio.Event(), asyncio.Event()
    client, scheduler = MagicMock(), MagicMock()
    http = AsyncMock()
    http.__aenter__.return_value = http

    async def blocked_poll(*args):
        assert args[-1] is http
        started.set()
        await release.wait()
        client.close.assert_not_called()
        http.__aexit__.assert_not_awaited()

    with patch.object(calendar_main, "GoogleCalendarClient", return_value=client), \
         patch.object(calendar_main, "AsyncIOScheduler", return_value=scheduler), \
         patch.object(calendar_main.httpx, "AsyncClient", return_value=http) as factory, \
         patch.object(calendar_main, "poll_google_calendar", side_effect=blocked_poll) as poll:
        async with calendar_main.lifespan(calendar_main.app):
            await calendar_main.poll_now()
            await started.wait()
            for _ in range(1000):
                await calendar_main.poll_now()
            poll.assert_awaited_once()
            factory.assert_called_once()
            release.set()
        client.close.assert_called_once()
        http.__aexit__.assert_awaited_once()
