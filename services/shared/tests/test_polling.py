import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.polling import PollRunner


@pytest.mark.asyncio
async def test_refresh_storm_owns_one_poll_and_shutdown_drains_it():
    started, release = asyncio.Event(), asyncio.Event()

    async def poll():
        started.set()
        await release.wait()

    callback = AsyncMock(side_effect=poll)
    runner = PollRunner(callback, MagicMock())
    runner.request()
    await started.wait()
    for _ in range(10000):
        runner.request()
    callback.assert_awaited_once()

    closing = asyncio.create_task(runner.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    runner.request()
    await asyncio.sleep(0)
    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelling_scheduler_does_not_abandon_poll():
    started, release = asyncio.Event(), asyncio.Event()
    completed = []

    async def poll():
        started.set()
        await release.wait()
        completed.append(True)

    runner = PollRunner(poll, MagicMock())
    scheduled = asyncio.create_task(runner.run())
    await started.wait()
    scheduled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await scheduled
    release.set()
    await runner.close()
    assert completed == [True]


@pytest.mark.asyncio
async def test_completed_or_failed_poll_can_be_requested_again():
    callback = AsyncMock(side_effect=[ValueError("bad response"), None])
    logger = MagicMock()
    runner = PollRunner(callback, logger)
    await runner.run()
    await runner.run()
    await runner.close()
    assert callback.await_count == 2
    logger.exception.assert_called_once()
