import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from shared.models import UnifiedEvent
from aggregator.queue import TickerQueue
from aggregator.drain import ticker_drain_loop


def _event(event_id: str, expired: bool = False) -> UnifiedEvent:
    ts = (
        datetime.now(timezone.utc) - timedelta(seconds=120)
        if expired
        else datetime.now(timezone.utc)
    )
    return UnifiedEvent(
        event_id=event_id, source="test", event_type="ticker",
        timestamp=ts, priority=1,
        ttl_seconds=60, payload={"text": event_id},
    )


@pytest.mark.asyncio
@patch("aggregator.drain.dispatch_command_to_transport", new_callable=AsyncMock)
@patch("aggregator.drain.TICKER_DRAIN_INTERVAL_SECONDS", 0.01)
async def test_drain_dispatches_valid_event(mock_dispatch):
    q = TickerQueue()
    await q.enqueue(_event("good"))
    task = asyncio.create_task(ticker_drain_loop(q, "http://mock-transport:8002"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    mock_dispatch.assert_awaited()


@pytest.mark.asyncio
@patch("aggregator.drain.dispatch_command_to_transport", new_callable=AsyncMock)
@patch("aggregator.drain.TICKER_DRAIN_INTERVAL_SECONDS", 0.01)
async def test_drain_skips_expired_event(mock_dispatch):
    q = TickerQueue()
    await q.enqueue(_event("expired", expired=True))
    task = asyncio.create_task(ticker_drain_loop(q, "http://mock-transport:8002"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    mock_dispatch.assert_not_awaited()
