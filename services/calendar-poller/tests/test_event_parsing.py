"""All-day detection and the recurring-event expansion parameter.

Added after mutation testing: `"date" in start and "dateTime" not in start`
could be flipped to `or`, and `singleEvents: "True"` to `"False"`, with the
whole suite still green. The first mislabels every timed event as all-day; the
second makes Google return recurring series masters instead of instances, so
the panel would show one entry for a weekly meeting instead of this week's.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from calendar_poller.calendar_client import GoogleCalendarClient


def _client() -> GoogleCalendarClient:
    client = GoogleCalendarClient.__new__(GoogleCalendarClient)
    client._calendar_ids = ["primary"]
    client._credentials = MagicMock(token="tok")
    client._logger = MagicMock()
    client._ensure_valid_token = MagicMock()
    return client


def _respond(items: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json = MagicMock(return_value={"items": items})
    http = MagicMock()
    http.get = MagicMock(return_value=resp)
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    return http


def _fetch(items: list[dict]):
    http = _respond(items)
    with patch("calendar_poller.calendar_client.httpx.Client", return_value=http):
        events = _client().fetch_events(
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 31, tzinfo=timezone.utc),
        )
    return events, http


def test_timed_event_is_not_all_day():
    events, _ = _fetch([{
        "id": "e1", "summary": "Standup",
        "start": {"dateTime": "2026-08-15T09:00:00Z"},
        "end": {"dateTime": "2026-08-15T09:15:00Z"},
    }])

    assert len(events) == 1
    assert events[0].all_day is False
    assert events[0].start == "2026-08-15T09:00:00Z"
    assert events[0].summary == "Standup"


def test_date_only_event_is_all_day():
    events, _ = _fetch([{
        "id": "e2", "summary": "Holiday",
        "start": {"date": "2026-08-15"},
        "end": {"date": "2026-08-16"},
    }])

    assert events[0].all_day is True
    assert events[0].start == "2026-08-15"


def test_recurring_events_are_requested_as_instances():
    """singleEvents=True expands a recurring series into individual dates."""
    _, http = _fetch([])
    params = http.get.call_args.kwargs["params"]

    assert params["singleEvents"] == "True"
    assert params["orderBy"] == "startTime"


def test_time_window_is_passed_through():
    _, http = _fetch([])
    params = http.get.call_args.kwargs["params"]

    assert params["timeMin"] == "2026-08-01T00:00:00Z"
    assert params["timeMax"] == "2026-08-31T00:00:00Z"


def test_both_date_and_datetime_present_is_treated_as_timed():
    """The only input that distinguishes `and` from `or` in the all-day check.
    With one key present both operators agree, so a mutation here survived the
    obvious tests. When Google supplies both, dateTime is the specific one and
    must win, otherwise a timed meeting renders as an all-day banner."""
    events, _ = _fetch([{
        "id": "e3", "summary": "Ambiguous",
        "start": {"date": "2026-08-15", "dateTime": "2026-08-15T09:00:00Z"},
        "end": {"date": "2026-08-16", "dateTime": "2026-08-15T10:00:00Z"},
    }])

    assert events[0].all_day is False
    assert events[0].start == "2026-08-15T09:00:00Z"
