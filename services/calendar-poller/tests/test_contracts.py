"""Runtime contracts at the untyped Google API boundary and object lifetimes."""
from __future__ import annotations

import gc
import json
import logging
import os
import weakref
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from google.auth.exceptions import RefreshError

from calendar_poller.calendar_client import (
    CalendarAPIError,
    CalendarPayloadError,
    GoogleCalendarClient,
)
from calendar_poller.poller import CalendarPollerState, poll_google_calendar
from shared.metrics import SourceMetrics
from shared.models import CalendarEvent
from shared.polling import PollRunner


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
EVENT = {
    "id": "one", "summary": "Appointment",
    "start": {"dateTime": "2026-10-10T10:00:00Z"},
    "end": {"dateTime": "2026-10-10T11:00:00Z"},
}


@pytest.fixture
def client():
    with patch("google.auth.default", return_value=(MagicMock(valid=True, token="fake"), "test")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "one,two"}), \
         closing(GoogleCalendarClient()) as client:
        yield client


@pytest.mark.parametrize("payload", [
    None, [], {"items": None}, {"items": {}}, {"items": [None]},
    {"items": [{**EVENT, "start": None}]},
    {"items": [{**EVENT, "end": []}]},
    {"items": [{**EVENT, "id": 42}]},
    {"items": [{**EVENT, "summary": None}]},
    {"items": [{**EVENT, "start": {"dateTime": None}}]},
    {"items": [{**EVENT, "end": {"dateTime": 123}}]},
])
def test_invalid_payload_never_constructs_mistyped_events(client, payload):
    with patch.object(client._http_client, "get", return_value=httpx.Response(200, content=json.dumps(payload))):
        with pytest.raises(CalendarPayloadError):
            client.fetch_events(NOW, NOW)


def test_all_calendars_failing_is_not_an_empty_success(client):
    with patch.object(client._http_client, "get", return_value=httpx.Response(503, text="unavailable")):
        with pytest.raises(CalendarAPIError, match="unavailable"):
            client.fetch_events(NOW, NOW)


def test_successful_empty_calendar_still_allows_partial_results(client):
    responses = [httpx.Response(503, text="unavailable"), httpx.Response(200, json={"items": []})]
    with patch.object(client._http_client, "get", side_effect=responses):
        assert client.fetch_events(NOW, NOW) == []


def test_time_window_offsets_are_converted_to_utc(client):
    local = datetime(2026, 10, 10, 9, tzinfo=timezone(timedelta(hours=-7)))
    with patch.object(client._http_client, "get", return_value=httpx.Response(200, json={})) as get:
        client.fetch_events(local, local + timedelta(hours=1))
    assert get.call_args.kwargs["params"]["timeMin"] == "2026-10-10T16:00:00Z"
    assert get.call_args.kwargs["params"]["timeMax"] == "2026-10-10T17:00:00Z"


def test_auth_session_is_closed_even_if_http_close_fails(client):
    with patch.object(client._http_client, "close", side_effect=RuntimeError("close failed")), \
         patch.object(client._auth_session, "close") as close:
        with pytest.raises(RuntimeError, match="close failed"):
            client.close()
        close.assert_called_once()


def test_failed_fetches_release_http_responses(client):
    responses = []

    def respond(request):
        response = httpx.Response(503, text="unavailable")
        responses.append(weakref.ref(response))
        return response

    client._http_client.close()
    client._http_client = httpx.Client(transport=httpx.MockTransport(respond))
    for _ in range(200):
        with pytest.raises(CalendarAPIError):
            client.fetch_events(NOW, NOW)
    gc.collect()
    assert len(responses) == 400
    assert all(ref() is None for ref in responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("private upstream URL"),
    RefreshError("private auth response"),
    CalendarPayloadError("invalid field"),
    ValueError("private JSON response"),
])
async def test_fetch_failures_are_counted_without_replacing_state(error, caplog):
    previous = [CalendarEvent("old", "Previous", "start", "end", False)]
    state = CalendarPollerState(previous, NOW, 1)
    metrics = SourceMetrics("calendar")
    client = MagicMock()
    client.fetch_events.side_effect = error
    logger = logging.getLogger("calendar-contract")
    with patch("calendar_poller.poller.metrics", metrics), \
         patch("calendar_poller.poller.push_calendar_update", new_callable=AsyncMock) as push:
        await poll_google_calendar(client, state, "http://aggregator", logger)
    assert state.last_events is previous
    assert state.last_poll_timestamp == NOW
    assert state.last_poll_event_count == 1
    assert metrics.poll_failure_total == 1
    assert metrics.poll_success_total == 0
    push.assert_not_awaited()
    assert "private" not in caplog.text


@pytest.mark.asyncio
async def test_repeated_polls_release_old_events_and_http_responses(client):
    responses = []
    events = []

    def respond(request):
        response = httpx.Response(200, json={"items": [EVENT]})
        responses.append(weakref.ref(response))
        return response

    state = CalendarPollerState()
    logger = logging.getLogger("calendar-retention")
    client._http_client.close()
    client._http_client = httpx.Client(transport=httpx.MockTransport(respond))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as downstream:
        runner = PollRunner(
            lambda: poll_google_calendar(client, state, "http://aggregator", logger, downstream),
            logger,
        )
        try:
            for _ in range(200):
                await runner.run()
                assert len(state.last_events) == 2
                events.extend(weakref.ref(event) for event in state.last_events)
        finally:
            await runner.close()
    gc.collect()
    assert len(events) == 400
    assert sum(ref() is not None for ref in events) == 2
    assert len(responses) == 600
    assert all(ref() is None for ref in responses)
