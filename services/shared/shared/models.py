from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    ticker = "ticker"
    doorbell_interrupt = "doorbell_interrupt"
    weather_update = "weather_update"
    calendar_update = "calendar_update"


class AlertType(str, Enum):
    temperature = "temperature"
    humidity = "humidity"
    system = "system"
    network = "network"


class AlertSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class WeatherProvider(str, Enum):
    google = "google"
    openweathermap = "openweathermap"


@dataclass
class UnifiedEvent:
    event_id: str
    source: str
    event_type: str        # string literal, not EventType enum — matches HTTP payload wire format
    timestamp: datetime
    priority: int
    ttl_seconds: int
    payload: dict
    dedup_hash: str | None = None


@dataclass
class WeatherConditions:
    provider: str
    timestamp: datetime
    temperature_c: float
    conditions: str
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    icon_code: str | None = None


@dataclass
class CalendarEvent:
    event_id: str
    summary: str
    start: str
    end: str
    all_day: bool


@dataclass
class CalendarState:
    poll_timestamp: datetime
    events: list[CalendarEvent] = field(default_factory=list)


@dataclass
class InternalEventRequest:
    """HTTP body for POST /internal/events on the aggregator."""
    source: str
    event_type: str
    timestamp: str           # ISO8601 string over the wire
    priority: int
    payload: dict
    ttl_seconds: int = 60


@dataclass
class CommandRequest:
    """HTTP body for POST /internal/commands on the transport adapter."""
    cmd: str                 # DOORBELL, TICKER-APPEND, WEATHER-UPDATE, CALENDAR-UPDATE
    priority: int
    payload: dict
    event_id: str
