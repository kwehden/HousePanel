"""Weather must poll on startup, not one interval later.

Weather's interval is 900s, so without an immediate first run a restart would
leave the panel with no weather for 15 minutes. Guards the same convention
that calendar-poller was silently missing.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from weather_poller import main as weather_main

_ENV = {
    "GOOGLE_WEATHER_API_KEY": "g", "GOOGLE_WEATHER_LOCATION": "0,0",
    "OPENWEATHERMAP_API_KEY": "o", "OPENWEATHERMAP_LOCATION": "London",
    "WTTR_LOCATION": "",
}


async def _enter_lifespan() -> MagicMock:
    scheduler = MagicMock()
    with patch.dict("os.environ", _ENV, clear=True), \
         patch.object(weather_main, "AsyncIOScheduler", return_value=scheduler):
        app = MagicMock()
        app.state = MagicMock()
        async with weather_main.lifespan(app):
            pass
    return scheduler


def _job(scheduler: MagicMock, job_id: str):
    for call in scheduler.add_job.call_args_list:
        if call.kwargs.get("id") == job_id:
            return call
    raise AssertionError(f"no job scheduled with id {job_id}")


@pytest.mark.asyncio
async def test_first_poll_is_scheduled_immediately():
    scheduler = await _enter_lifespan()
    assert _job(scheduler, "poll_weather").kwargs.get("next_run_time") is not None


@pytest.mark.asyncio
async def test_midnight_refresh_job_is_registered():
    """The daily cron exists to roll the forecast over at local midnight."""
    scheduler = await _enter_lifespan()
    kwargs = _job(scheduler, "poll_weather_midnight").kwargs
    assert kwargs["trigger"] == "cron"
    assert (kwargs["hour"], kwargs["minute"]) == (0, 5)


@pytest.mark.asyncio
async def test_poll_interval_is_published_to_metrics():
    """The staleness alert reads this value, so it must track the real interval."""
    await _enter_lifespan()
    from weather_poller.poller import metrics
    assert metrics.poll_interval_seconds == 900
