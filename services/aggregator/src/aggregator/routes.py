from __future__ import annotations
import asyncio
import os
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from shared.models import InternalEventRequest
from shared.logging import make_logger, log_event
from .queue import TickerQueue
from .dedup import DedupCache
from .state import AggregatorState
from .router import route_event

router = APIRouter()
logger = make_logger("aggregator")

# Singletons — instantiated once in main.py and injected via closure
_queue: TickerQueue | None = None
_dedup: DedupCache | None = None
_state: AggregatorState | None = None


def init_singletons(queue: TickerQueue, dedup: DedupCache, state: AggregatorState) -> None:
    global _queue, _dedup, _state
    _queue, _dedup, _state = queue, dedup, state


@router.post("/internal/events", status_code=202)
async def internal_events(req: InternalEventRequest) -> JSONResponse:
    await route_event(req, _state, _queue, _dedup)
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/internal/state")
async def internal_state() -> dict:
    ticker_snapshot = await _queue.snapshot()
    return {
        **_state.to_dict(),
        "ticker_queue": [
            {
                "event_id": e.event_id,
                "source": e.source,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "payload": e.payload,
            }
            for e in ticker_snapshot
        ],
    }


@router.get("/internal/health")
async def internal_health() -> dict:
    snapshot = await _queue.snapshot()
    return {"queue_depth": len(snapshot), "status": "ok"}


@router.post("/internal/refresh", status_code=202)
async def internal_refresh() -> JSONResponse:
    weather_url = os.environ.get("WEATHER_POLLER_URL", "http://housepanel-weather-poller:8004")
    calendar_url = os.environ.get("CALENDAR_POLLER_URL", "http://housepanel-calendar-poller:8003")

    async def _ping(url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(f"{url}/internal/poll-now")
        except Exception as exc:
            log_event(logger, "refresh_ping_failed", level="warning", url=url, error=str(exc))

    await asyncio.gather(_ping(weather_url), _ping(calendar_url))
    log_event(logger, "pollers_refreshed")
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
