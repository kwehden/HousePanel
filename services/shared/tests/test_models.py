from datetime import datetime, timezone
from shared.models import (
    UnifiedEvent, WeatherConditions, CalendarEvent, CalendarState,
    InternalEventRequest, CommandRequest, EventType, AlertSeverity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_unified_event_fields():
    e = UnifiedEvent(
        event_id="abc-123",
        source="ring",
        event_type="doorbell_interrupt",   # string, not EventType enum
        timestamp=_now(),
        priority=99,
        ttl_seconds=30,
        payload={"device_id": "d1"},
    )
    assert e.event_id == "abc-123"
    assert e.dedup_hash is None
    # event_type is a plain string on the wire, not an enum instance
    assert isinstance(e.event_type, str)


def test_unified_event_with_dedup_hash():
    e = UnifiedEvent(
        event_id="xyz",
        source="webhook",
        event_type="ticker",
        timestamp=_now(),
        priority=1,
        ttl_seconds=60,
        payload={},
        dedup_hash="sha256:abc",
    )
    assert e.dedup_hash == "sha256:abc"


def test_weather_conditions_optional_fields():
    w = WeatherConditions(
        provider="google",
        timestamp=_now(),
        temperature_c=21.5,
        conditions="Partly cloudy",
    )
    assert w.humidity_pct is None
    assert w.wind_speed_ms is None
    assert w.icon_code is None


def test_calendar_state_default_events():
    cs = CalendarState(poll_timestamp=_now())
    assert cs.events == []


def test_internal_event_request_defaults():
    r = InternalEventRequest(
        source="ring",
        event_type="doorbell_interrupt",
        timestamp="2026-05-17T00:00:00Z",
        priority=99,
        payload={},
    )
    assert r.ttl_seconds == 60


def test_event_type_enum_values():
    assert EventType.doorbell_interrupt == "doorbell_interrupt"
    assert EventType.ticker == "ticker"


def test_alert_severity_enum_values():
    assert AlertSeverity.critical == "critical"
