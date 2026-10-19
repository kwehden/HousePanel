from __future__ import annotations
import asyncio
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from shared.http import async_request
from pydantic import BaseModel, ConfigDict, Field
from shared.logging import make_logger, log_event
from shared.polling import PollRunner
from transport_adapter import state
from transport_adapter.stream_decompose import decompose_command
from shared.contracts import CalendarPayload, JsonObject, SysmonPayload, WeatherPayload

_PACIFIC = ZoneInfo("America/Los_Angeles")

logger = make_logger("transport-adapter")
_refresh_runner: PollRunner | None = None


class _TickerPayload(BaseModel):
    text: str = ""
    narrative: str | None = None
    ttl_seconds: int = Field(default=60, ge=0)


class _TickerEntry(BaseModel):
    payload: _TickerPayload = Field(default_factory=_TickerPayload)
    ttl_seconds: int | None = Field(default=None, ge=0)


class _Snapshot(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    weather: WeatherPayload | None = None
    calendar: CalendarPayload | None = None
    sysmon: SysmonPayload | None = None
    ticker_queue: list[_TickerEntry] = Field(default_factory=list)


def request_poller_refresh() -> None:
    global _refresh_runner
    if _refresh_runner is None:
        _refresh_runner = PollRunner(_trigger_poller_refresh, logger)
    _refresh_runner.request()


async def close_poller_refresh() -> None:
    global _refresh_runner
    if _refresh_runner is not None:
        await _refresh_runner.close()
        _refresh_runner = None


def discard_stale_commands(panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
    panel.normal_generation += 1
    panel.pending_normal = None
    if panel.normal_getter is not None and not panel.normal_getter.done():
        panel.normal_getter.cancel()
    while True:
        try:
            panel.normal_queue.get_nowait()
        except asyncio.QueueEmpty:
            break


async def handle_hello_frame(frame: JsonObject, *, normal_ready: asyncio.Event | None = None,
                             panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
    discard_stale_commands(panel)
    if normal_ready is not None:
        # Refresh may fill the bounded queue, so let its writer drain new frames.
        normal_ready.set()
    request_poller_refresh()
    await _refresh_state(triggered_by="hello", panel=panel)


async def _trigger_poller_refresh() -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await async_request(client, "POST", f"{state.AGGREGATOR_URL}/internal/refresh")
            resp.raise_for_status()
        log_event(logger, "poller_refresh_triggered")
    except Exception as exc:
        log_event(logger, "poller_refresh_trigger_failed", level="warning", error=str(exc))


async def handle_post_ota_refresh(panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
    discard_stale_commands(panel)
    await _refresh_state(triggered_by="post_ota", panel=panel)


async def _refresh_state(triggered_by: str, panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
    now_pacific = datetime.now(_PACIFIC)
    offset = now_pacific.utcoffset()
    assert offset is not None
    utc_offset_min = int(offset.total_seconds() / 60)
    await panel.normal_queue.put({"cmd": "TIME", "epoch": int(_time.time()), "utc_offset_min": utc_offset_min})

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await async_request(client, "GET", f"{state.AGGREGATOR_URL}/internal/state")
            resp.raise_for_status()
            data = _Snapshot.model_validate_json(resp.content)

        items: list[JsonObject] = []
        for cmd, payload in (
            ("WEATHER-UPDATE", data.weather),
            ("CALENDAR-UPDATE", data.calendar),
            ("SYSMON-UPDATE", data.sysmon),
        ):
            if payload is not None:
                items.extend(decompose_command(cmd, payload.model_dump()))
        for entry in data.ticker_queue:
            text = entry.payload.narrative or entry.payload.text
            if text:
                items.extend(decompose_command("TICKER-APPEND", {
                    "text": text,
                    "ttl_seconds": (entry.ttl_seconds if entry.ttl_seconds is not None
                                    else entry.payload.ttl_seconds),
                }))
    except Exception as exc:
        log_event(logger, "state_refresh_failed", level="warning",
                  triggered_by=triggered_by, error=str(exc))
        return

    for item in items:
        await panel.normal_queue.put(item)

    log_event(logger, "state_refreshed", triggered_by=triggered_by)
