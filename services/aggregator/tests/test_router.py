import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from shared.models import InternalEventRequest
from aggregator.queue import TickerQueue
from aggregator.dedup import DedupCache
from aggregator.state import AggregatorState
from aggregator.router import route_event


def _req(event_type: str, payload: dict | None = None, source: str = "test") -> InternalEventRequest:
    return InternalEventRequest(
        source=source, event_type=event_type,
        timestamp="2026-05-17T00:00:00Z", priority=1,
        payload=payload or {},
    )


@pytest.mark.asyncio
@patch("aggregator.router.dispatch_command_to_transport", new_callable=AsyncMock)
async def test_doorbell_dispatched_inline(mock_dispatch):
    q, d, s = TickerQueue(), DedupCache(), AggregatorState()
    await route_event(_req("doorbell-interrupt", {"device_id": "d1"}), s, q, d)
    mock_dispatch.assert_awaited_once()
    call_kwargs = mock_dispatch.call_args
    assert call_kwargs.kwargs["cmd"] == "DOORBELL" or call_kwargs.args[0] == "DOORBELL"
    # Must NOT be enqueued
    snapshot = await q.snapshot()
    assert len(snapshot) == 0


@pytest.mark.asyncio
@patch("aggregator.router.dispatch_command_to_transport", new_callable=AsyncMock)
async def test_ticker_enqueued(mock_dispatch):
    q, d, s = TickerQueue(), DedupCache(), AggregatorState()
    await route_event(_req("ticker", {"narrative": "A person walked by"}), s, q, d)
    mock_dispatch.assert_not_awaited()
    snapshot = await q.snapshot()
    assert len(snapshot) == 1


@pytest.mark.asyncio
@patch("aggregator.router.dispatch_command_to_transport", new_callable=AsyncMock)
async def test_ticker_dedup_rejected(mock_dispatch):
    q, d, s = TickerQueue(), DedupCache(), AggregatorState()
    req = _req("ticker", {"narrative": "Same event"})
    await route_event(req, s, q, d)
    await route_event(req, s, q, d)  # duplicate
    snapshot = await q.snapshot()
    assert len(snapshot) == 1  # only first accepted


@pytest.mark.asyncio
@patch("aggregator.router.dispatch_command_to_transport", new_callable=AsyncMock)
async def test_weather_update_state(mock_dispatch):
    q, d, s = TickerQueue(), DedupCache(), AggregatorState()
    await route_event(_req("weather-update", {"temperature_c": 22.0, "conditions": "Sunny", "provider": "google"}), s, q, d)
    assert s.last_weather is not None
    assert s.last_weather.temperature_c == 22.0
    mock_dispatch.assert_awaited_once()


@pytest.mark.asyncio
@patch("aggregator.router.dispatch_command_to_transport", new_callable=AsyncMock)
async def test_calendar_update_state(mock_dispatch):
    q, d, s = TickerQueue(), DedupCache(), AggregatorState()
    await route_event(_req("calendar-update", {"events": []}), s, q, d)
    assert s.last_calendar is not None
    mock_dispatch.assert_awaited_once()
