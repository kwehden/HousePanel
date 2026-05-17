from __future__ import annotations
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


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
