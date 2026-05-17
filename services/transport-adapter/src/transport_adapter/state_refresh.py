from __future__ import annotations
import httpx
from uuid import uuid4
from shared.logging import make_logger, log_event
from transport_adapter import state

logger = make_logger("transport-adapter")


async def handle_hello_frame(frame: dict) -> None:
    await _refresh_state(triggered_by="hello")


async def handle_post_ota_refresh() -> None:
    await _refresh_state(triggered_by="post_ota")


async def _refresh_state(triggered_by: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{state.AGGREGATOR_URL}/internal/state")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log_event(logger, "state_refresh_failed", level="warning",
                  triggered_by=triggered_by, error=str(exc))
        return

    weather = data.get("weather")
    if weather:
        cmd = {
            "cmd": "WEATHER-UPDATE",
            "message_id": str(uuid4()),
            "temperature_c": weather.get("temperature_c"),
            "conditions": weather.get("conditions"),
            "humidity_pct": weather.get("humidity_pct"),
            "wind_speed_ms": weather.get("wind_speed_ms"),
            "icon_code": weather.get("icon_code"),
        }
        await state.normal_queue.put(cmd)

    calendar = data.get("calendar")
    if calendar:
        cmd = {
            "cmd": "CALENDAR-UPDATE",
            "message_id": str(uuid4()),
            "events": calendar.get("events", []),
        }
        await state.normal_queue.put(cmd)

    ticker_queue = data.get("ticker_queue", [])
    for entry in ticker_queue:
        payload = entry.get("payload", {})
        text = payload.get("narrative") or payload.get("text") or ""
        if not text:
            continue
        ttl = entry.get("ttl_seconds", 60)
        cmd = {
            "cmd": "TICKER-APPEND",
            "message_id": str(uuid4()),
            "text": text,
            "ttl_seconds": ttl,
        }
        await state.normal_queue.put(cmd)

    log_event(logger, "state_refreshed", triggered_by=triggered_by)
