"""sysmon must poll on startup, not one interval later.

Guards the same convention that calendar-poller was silently missing: every
poller schedules its first run immediately, so a restart does not blank the
panel for a full interval.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sysmon_poller import main as sysmon_main


async def _enter_lifespan() -> MagicMock:
    scheduler = MagicMock()
    with patch.object(sysmon_main, "AsyncIOScheduler", return_value=scheduler):
        async with sysmon_main.lifespan(MagicMock()):
            pass
    return scheduler


@pytest.mark.asyncio
async def test_first_poll_is_scheduled_immediately():
    scheduler = await _enter_lifespan()
    assert scheduler.add_job.call_args.kwargs.get("next_run_time") is not None


@pytest.mark.asyncio
async def test_interval_matches_configuration():
    scheduler = await _enter_lifespan()
    assert scheduler.add_job.call_args.kwargs["seconds"] == sysmon_main._POLL_INTERVAL


@pytest.mark.asyncio
async def test_scheduler_is_started_and_stopped():
    scheduler = await _enter_lifespan()
    scheduler.start.assert_called_once()
    scheduler.shutdown.assert_called_once()
