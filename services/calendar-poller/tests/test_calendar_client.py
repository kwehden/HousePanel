"""Tests for calendar_poller.calendar_client."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from shared.models import CalendarEvent

from calendar_poller.calendar_client import CalendarAPIError, GoogleCalendarClient


_FAKE_CALENDAR_RESPONSE = {
    "items": [
        {
            "id": "evt-001",
            "summary": "Team standup",
            "start": {"dateTime": "2026-05-20T09:00:00Z"},
            "end": {"dateTime": "2026-05-20T09:30:00Z"},
        },
        {
            "id": "evt-002",
            "summary": "Holiday",
            "start": {"date": "2026-05-21"},
            "end": {"date": "2026-05-22"},
        },
    ]
}


def _mock_credentials(valid: bool = True) -> MagicMock:
    creds = MagicMock()
    creds.valid = valid
    creds.token = "fake-access-token"
    return creds


def test_client_instantiates_with_mocked_adc() -> None:
    """GoogleCalendarClient can be instantiated when google.auth.default is mocked."""
    mock_creds = _mock_credentials()
    with patch("google.auth.default", return_value=(mock_creds, "test-project")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "test@group.calendar.google.com"}):
        client = GoogleCalendarClient()
    assert client is not None


def test_fetch_events_parses_response_correctly() -> None:
    """fetch_events returns correct CalendarEvent list; all_day set for date-only items."""
    mock_creds = _mock_credentials(valid=True)
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = _FAKE_CALENDAR_RESPONSE

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.get = MagicMock(return_value=mock_response)

    with patch("google.auth.default", return_value=(mock_creds, "test-project")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "test@group.calendar.google.com"}), \
         patch("calendar_poller.calendar_client.httpx.Client", return_value=mock_http_instance):
        client = GoogleCalendarClient()
        from datetime import datetime
        events = client.fetch_events(
            datetime(2026, 5, 20, 0, 0, 0),
            datetime(2026, 5, 27, 0, 0, 0),
        )

    assert len(events) == 2
    timed_event = events[0]
    assert isinstance(timed_event, CalendarEvent)
    assert timed_event.event_id == "evt-001"
    assert timed_event.all_day is False
    assert timed_event.start == "2026-05-20T09:00:00Z"

    all_day_event = events[1]
    assert all_day_event.event_id == "evt-002"
    assert all_day_event.all_day is True
    assert all_day_event.start == "2026-05-21"


def test_event_summary_not_logged(capsys: pytest.CaptureFixture) -> None:
    """fetch_events must not log the summary of any calendar event."""
    mock_creds = _mock_credentials(valid=True)
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = _FAKE_CALENDAR_RESPONSE

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.get = MagicMock(return_value=mock_response)

    with patch("google.auth.default", return_value=(mock_creds, "test-project")), \
         patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "test@group.calendar.google.com"}), \
         patch("calendar_poller.calendar_client.httpx.Client", return_value=mock_http_instance):
        client = GoogleCalendarClient()
        from datetime import datetime
        client.fetch_events(
            datetime(2026, 5, 20, 0, 0, 0),
            datetime(2026, 5, 27, 0, 0, 0),
        )

    captured = capsys.readouterr()
    log_output = captured.out

    for item in _FAKE_CALENDAR_RESPONSE["items"]:
        summary = item["summary"]
        assert summary not in log_output, (
            f"Event summary '{summary}' must not appear in log output"
        )
    assert "test@group.calendar.google.com" not in log_output, (
        "GOOGLE_CALENDAR_ID must not appear in log output"
    )
