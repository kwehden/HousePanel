"""Tests for calendar_poller.poller."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.models import CalendarEvent

from calendar_poller.calendar_client import CalendarAPIError
from calendar_poller.poller import CalendarPollerState, poll_google_calendar


def _make_events(n: int = 2) -> list[CalendarEvent]:
    return [
        CalendarEvent(
            event_id=f"evt-{i}",
            summary=f"Event {i}",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            all_day=False,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_poll_success_updates_state_and_pushes() -> None:
    """Poll success: state updated; push called with correct event_count."""
    events = _make_events(2)
    mock_client = MagicMock()
    mock_client.fetch_events.return_value = events

    state = CalendarPollerState()
    logger = logging.getLogger("test-poller")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    mock_async_client_instance = AsyncMock()
    mock_async_client_instance.__aenter__ = AsyncMock(return_value=mock_async_client_instance)
    mock_async_client_instance.__aexit__ = AsyncMock(return_value=False)
    mock_async_client_instance.post = AsyncMock(return_value=mock_response)

    with patch("calendar_poller.poller.httpx.AsyncClient", return_value=mock_async_client_instance):
        await poll_google_calendar(mock_client, state, "http://aggregator:8001", logger)

    assert state.last_poll_event_count == len(events)
    assert state.last_events == events
    assert state.last_poll_timestamp is not None
    mock_async_client_instance.post.assert_called_once()
    body = mock_async_client_instance.post.call_args.kwargs["json"]
    assert len(body["payload"]["events"]) == 2
    assert body["event_type"] == "calendar-update"
    assert body["source"] == "calendar-poller"


@pytest.mark.asyncio
async def test_poll_error_retains_last_events(caplog: pytest.LogCaptureFixture) -> None:
    """CalendarAPIError: last_events unchanged; error logged."""
    existing_events = _make_events(1)
    state = CalendarPollerState(
        last_events=existing_events,
        last_poll_timestamp=None,
        last_poll_event_count=1,
    )

    mock_client = MagicMock()
    mock_client.fetch_events.side_effect = CalendarAPIError(503, "unavailable")

    logger = logging.getLogger("test-poller-error")

    with caplog.at_level(logging.ERROR, logger="test-poller-error"):
        await poll_google_calendar(mock_client, state, "http://aggregator:8001", logger)

    assert state.last_events == existing_events, "last_events must not change on error"
    assert any("poll_error" in r.getMessage() for r in caplog.records), (
        "Expected poll_error log record"
    )
