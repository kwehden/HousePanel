"""sysmon must poll on startup, not one interval later.

Guards the same convention that calendar-poller was silently missing: every
poller schedules its first run immediately, so a restart does not blank the
panel for a full interval.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_poll_cycles_share_one_client_closed_on_shutdown():
    scheduler = MagicMock()
    client = AsyncMock()
    client.__aenter__.return_value = client
    with patch.object(sysmon_main, "AsyncIOScheduler", return_value=scheduler), \
         patch.object(sysmon_main.httpx, "AsyncClient", return_value=client) as factory, \
         patch.object(sysmon_main, "_poll", new_callable=AsyncMock) as poll:
        async with sysmon_main.lifespan(MagicMock()):
            run = scheduler.add_job.call_args.args[0]
            for _ in range(100):
                await run()
            assert poll.await_count == 100
            assert all(call.args == (client,) for call in poll.await_args_list)
            factory.assert_called_once()
            client.__aexit__.assert_not_awaited()
        client.__aexit__.assert_awaited_once()
