from __future__ import annotations
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from shared.logging import make_logger, log_event
from transport_adapter import state
from transport_adapter.stream_decompose import decompose_command
from uuid import uuid4

_PACIFIC = ZoneInfo("America/Los_Angeles")

logger = make_logger("transport-adapter")


async def handle_hello_frame(frame: dict) -> None:
    await _refresh_state(triggered_by="hello")


async def handle_post_ota_refresh() -> None:
    await _refresh_state(triggered_by="post_ota")


async def _refresh_state(triggered_by: str) -> None:
    now_pacific = datetime.now(_PACIFIC)
    utc_offset_min = int(now_pacific.utcoffset().total_seconds() / 60)
    await state.normal_queue.put({"cmd": "TIME", "epoch": int(_time.time()), "utc_offset_min": utc_offset_min})

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
        for item in decompose_command("WEATHER-UPDATE", weather):
            await state.normal_queue.put(item)

    calendar = data.get("calendar")
    if calendar:
        for item in decompose_command("CALENDAR-UPDATE", calendar):
            await state.normal_queue.put(item)

    sysmon = data.get("sysmon")
    if sysmon:
        for item in decompose_command("SYSMON-UPDATE", sysmon):
            await state.normal_queue.put(item)

    ticker_queue = data.get("ticker_queue", [])
    for entry in ticker_queue:
        payload = entry.get("payload", {})
        text = payload.get("narrative") or payload.get("text") or ""
        if not text:
            continue
        await state.normal_queue.put({
            "cmd": "TICKER-APPEND",
            "text": text,
            "ttl_seconds": entry.get("ttl_seconds", 60),
        })

    log_event(logger, "state_refreshed", triggered_by=triggered_by)
