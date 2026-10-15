from __future__ import annotations

import os
import json
from datetime import datetime, timezone

import google.auth
import google.auth.transport.requests
import httpx
import requests

from shared.logging import log_event, make_logger
from shared.models import CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars"


class CalendarAPIError(Exception):
    def __init__(self, http_status: int, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.message = message


class CalendarPayloadError(ValueError):
    """The upstream response does not satisfy the calendar event contract."""


def _event_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise CalendarPayloadError(f"Expected a string for {field}")
    return value


def _utc_timestamp(value: datetime) -> str:
    # Preserve the legacy convention that naive inputs represent UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class GoogleCalendarClient:
    def __init__(self) -> None:
        self._credentials, _ = google.auth.default(scopes=SCOPES)
        raw_ids = os.environ["GOOGLE_CALENDAR_ID"]
        self._calendar_ids = [cid.strip() for cid in raw_ids.split(",") if cid.strip()]
        self._logger = make_logger("calendar-poller")
        self._http_client = httpx.Client(timeout=10)
        self._auth_session = requests.Session()
        # Request.__del__ closes even a caller-owned session. Keep the wrapper
        # alive with the client so token refreshes do not tear down its pool.
        self._auth_request = google.auth.transport.requests.Request(session=self._auth_session)

    def close(self) -> None:
        try:
            self._http_client.close()
        finally:
            self._auth_session.close()

    def _ensure_valid_token(self) -> None:
        if not self._credentials.valid:
            # google-auth's refresh method has no parameter annotations.
            self._credentials.refresh(self._auth_request)  # type: ignore[no-untyped-call]

    def _fetch_from_calendar(
        self, calendar_id: str, params: dict[str, str], headers: dict[str, str]
    ) -> list[CalendarEvent]:
        url = f"{_CALENDAR_API_BASE}/{calendar_id}/events"
        # Buffered HTTPX responses participate in response/stream cycles. Read
        # into a local bounded buffer so bodies are not retained until cyclic GC.
        with self._http_client.stream("GET", url, params=params, headers=headers) as response:
            try:
                if not response.is_success:
                    preview = next(response.iter_bytes(chunk_size=200), b"")[:200]
                    raise CalendarAPIError(response.status_code, preview.decode(errors="replace"))
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=16384):
                    if len(raw) + len(chunk) > 1024 * 1024:
                        raise CalendarPayloadError("Calendar response exceeds 1 MiB")
                    raw.extend(chunk)
                payload: object = json.loads(raw)
            finally:
                response.close()
                # HTTPX's closed stream still references its response. Detach it
                # only after closing, releasing request/response cycles without GC.
                response.stream = httpx.ByteStream(b"")
        if not isinstance(payload, dict):
            raise CalendarPayloadError("Expected a calendar response object")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise CalendarPayloadError("Expected an items array")
        events: list[CalendarEvent] = []
        for item in items:
            if not isinstance(item, dict):
                raise CalendarPayloadError("Expected an event object")
            start = item.get("start", {})
            end = item.get("end", {})
            if not isinstance(start, dict) or not isinstance(end, dict):
                raise CalendarPayloadError("Expected start and end objects")
            all_day = "date" in start and "dateTime" not in start
            events.append(CalendarEvent(
                event_id=_event_text(item.get("id", ""), "id"),
                summary=_event_text(item.get("summary", ""), "summary"),
                start=_event_text(start.get("dateTime", start.get("date", "")), "start"),
                end=_event_text(end.get("dateTime", end.get("date", "")), "end"),
                all_day=all_day,
            ))
        return events

    def fetch_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        self._ensure_valid_token()
        params = {
            "timeMin": _utc_timestamp(time_min),
            "timeMax": _utc_timestamp(time_max),
            "singleEvents": "True",
            "orderBy": "startTime",
            "fields": "items(id,summary,start,end),nextPageToken",
        }
        headers = {"Authorization": f"Bearer {self._credentials.token}"}
        all_events: list[CalendarEvent] = []
        successful_calendars = 0
        last_error: tuple[int, str] | None = None
        for cal_id in self._calendar_ids:
            try:
                events = self._fetch_from_calendar(cal_id, params, headers)
                log_event(self._logger, "calendar_fetched",
                          calendar_id=cal_id[:40], event_count=len(events))
                all_events.extend(events)
                successful_calendars += 1
            except CalendarAPIError as exc:
                # Do not retain the exception's traceback and response frame.
                last_error = (exc.http_status, exc.message)
                log_event(self._logger, "calendar_fetch_error", level="warning",
                          calendar_id=cal_id[:40], http_status=exc.http_status,
                          error=exc.message[:120])
        if not successful_calendars and last_error is not None:
            raise CalendarAPIError(*last_error)
        all_events.sort(key=lambda e: e.start)
        log_event(self._logger, "fetch_events_success", event_count=len(all_events),
                  calendar_count=len(self._calendar_ids))
        return all_events
