from __future__ import annotations

import os
from datetime import datetime

import google.auth
import google.auth.transport.requests
import httpx

from shared.logging import log_event, make_logger
from shared.models import CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars"


class CalendarAPIError(Exception):
    def __init__(self, http_status: int, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.message = message


class GoogleCalendarClient:
    def __init__(self) -> None:
        self._credentials, _ = google.auth.default(scopes=SCOPES)
        raw_ids = os.environ["GOOGLE_CALENDAR_ID"]
        self._calendar_ids = [cid.strip() for cid in raw_ids.split(",") if cid.strip()]
        self._logger = make_logger("calendar-poller")

    def _ensure_valid_token(self) -> None:
        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())

    def _fetch_from_calendar(
        self, calendar_id: str, params: dict, headers: dict
    ) -> list[CalendarEvent]:
        url = f"{_CALENDAR_API_BASE}/{calendar_id}/events"
        with httpx.Client(timeout=10) as http_client:
            response = http_client.get(url, params=params, headers=headers)
        if not response.is_success:
            raise CalendarAPIError(response.status_code, response.text[:200])
        events: list[CalendarEvent] = []
        for item in response.json().get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            all_day = "date" in start and "dateTime" not in start
            events.append(CalendarEvent(
                event_id=item.get("id", ""),
                summary=item.get("summary", ""),
                start=start.get("dateTime", start.get("date", "")),
                end=end.get("dateTime", end.get("date", "")),
                all_day=all_day,
            ))
        return events

    def fetch_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        self._ensure_valid_token()
        params = {
            "timeMin": time_min.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeMax": time_max.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "singleEvents": "True",
            "orderBy": "startTime",
        }
        headers = {"Authorization": f"Bearer {self._credentials.token}"}
        all_events: list[CalendarEvent] = []
        for cal_id in self._calendar_ids:
            events = self._fetch_from_calendar(cal_id, params, headers)
            all_events.extend(events)
        all_events.sort(key=lambda e: e.start)
        log_event(self._logger, "fetch_events_success", event_count=len(all_events),
                  calendar_count=len(self._calendar_ids))
        return all_events
