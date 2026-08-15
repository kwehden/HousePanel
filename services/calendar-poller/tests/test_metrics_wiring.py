"""The recorder must be driven by the real poll/push paths, not just exist."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from calendar_poller.calendar_client import CalendarAPIError
from calendar_poller.poller import (
    CalendarPollerState,
    metrics,
    poll_google_calendar,
    push_calendar_update,
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.poll_success_total = 0
    metrics.poll_failure_total = 0
    metrics.push_success_total = 0
    metrics.push_failure_total = 0
    metrics.last_poll_success_wall = None
    metrics.last_push_success_wall = None
    yield


def _client(*, raises: Exception | None = None) -> MagicMock:
    client = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=raises)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_successful_push_advances_the_push_timestamp():
    with patch("calendar_poller.poller.httpx.AsyncClient", return_value=_client()):
        await push_calendar_update([], "http://agg", MagicMock())

    assert metrics.push_success_total == 1
    assert metrics.last_push_success_wall is not None


@pytest.mark.asyncio
async def test_failed_push_is_counted():
    client = _client(raises=RuntimeError("aggregator down"))
    with patch("calendar_poller.poller.httpx.AsyncClient", return_value=client):
        await push_calendar_update([], "http://agg", MagicMock())

    assert metrics.push_failure_total == 1
    assert metrics.last_push_success_wall is None


@pytest.mark.asyncio
async def test_poll_success_recorded():
    client = MagicMock()
    client.fetch_events.return_value = []

    with patch("calendar_poller.poller.push_calendar_update", new_callable=AsyncMock):
        await poll_google_calendar(client, CalendarPollerState(), "http://agg", MagicMock())

    assert metrics.poll_success_total == 1
    assert metrics.last_poll_success_wall is not None


@pytest.mark.asyncio
async def test_empty_calendar_is_a_success_not_a_failure():
    """No events is a valid answer — an empty week must not read as broken."""
    client = MagicMock()
    client.fetch_events.return_value = []

    with patch("calendar_poller.poller.push_calendar_update", new_callable=AsyncMock):
        await poll_google_calendar(client, CalendarPollerState(), "http://agg", MagicMock())

    assert metrics.poll_failure_total == 0
    assert metrics.poll_success_total == 1


@pytest.mark.asyncio
async def test_api_error_records_a_poll_failure():
    client = MagicMock()
    client.fetch_events.side_effect = CalendarAPIError(http_status=403, message="denied")

    await poll_google_calendar(client, CalendarPollerState(), "http://agg", MagicMock())

    assert metrics.poll_failure_total == 1
    assert metrics.poll_success_total == 0
