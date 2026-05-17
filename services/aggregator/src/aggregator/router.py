from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone
from shared.models import UnifiedEvent, InternalEventRequest
from shared.logging import make_logger, log_event
from .queue import TickerQueue
from .dedup import DedupCache
from .state import AggregatorState
from .transport_client import dispatch_command_to_transport

logger = make_logger("aggregator")


async def route_event(
    event_req: InternalEventRequest,
    state: AggregatorState,
    queue: TickerQueue,
    dedup: DedupCache,
) -> None:
    event_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc)

    if event_req.event_type == "doorbell-interrupt":
        # CRITICAL: dispatch inline before returning — do NOT enqueue
        log_event(logger, "doorbell_routed", event_id=event_id, source=event_req.source)
        await dispatch_command_to_transport(
            cmd="DOORBELL",
            priority=99,
            payload=event_req.payload,
            event_id=event_id,
        )
        return

    if event_req.event_type == "weather-update":
        from shared.models import WeatherConditions, ForecastDay
        w = WeatherConditions(
            provider=event_req.payload.get("provider", "unknown"),
            timestamp=ts,
            temperature_c=event_req.payload.get("temperature_c", 0.0),
            conditions=event_req.payload.get("conditions", ""),
            humidity_pct=event_req.payload.get("humidity_pct"),
            wind_speed_ms=event_req.payload.get("wind_speed_ms"),
            icon_code=event_req.payload.get("icon_code"),
            today_high_c=event_req.payload.get("today_high_c"),
            today_low_c=event_req.payload.get("today_low_c"),
            forecast=[
                ForecastDay(
                    day_label=d.get("day_label", ""),
                    high_c=d.get("high_c", 0.0),
                    low_c=d.get("low_c", 0.0),
                    conditions=d.get("conditions", ""),
                )
                for d in event_req.payload.get("forecast", [])
            ],
        )
        state.update_weather(w)
        await dispatch_command_to_transport(
            cmd="WEATHER-UPDATE",
            priority=5,
            payload=state.to_dict()["weather"],
            event_id=event_id,
        )
        return

    if event_req.event_type == "calendar-update":
        from shared.models import CalendarState, CalendarEvent
        events = [
            CalendarEvent(
                event_id=e.get("event_id", ""),
                summary=e.get("summary", ""),
                start=e.get("start", ""),
                end=e.get("end", ""),
                all_day=e.get("all_day", False),
            )
            for e in event_req.payload.get("events", [])
        ]
        c = CalendarState(poll_timestamp=ts, events=events)
        state.update_calendar(c)
        await dispatch_command_to_transport(
            cmd="CALENDAR-UPDATE",
            priority=5,
            payload=state.to_dict()["calendar"],
            event_id=event_id,
        )
        return

    # ticker event
    dedup_hash = hashlib.sha256(
        (event_req.source + json.dumps(event_req.payload, sort_keys=True)).encode()
    ).hexdigest()

    if dedup.is_duplicate(dedup_hash):
        log_event(logger, "ticker_dropped_dedup", source=event_req.source, dedup_hash=dedup_hash[:16])
        return

    dedup.record(dedup_hash)
    unified = UnifiedEvent(
        event_id=event_id,
        source=event_req.source,
        event_type=event_req.event_type,
        timestamp=ts,
        priority=event_req.priority,
        ttl_seconds=event_req.ttl_seconds,
        payload=event_req.payload,
        dedup_hash=dedup_hash,
    )
    await queue.enqueue(unified)
    log_event(logger, "ticker_enqueued", event_id=event_id, source=event_req.source)
