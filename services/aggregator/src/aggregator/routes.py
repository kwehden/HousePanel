from __future__ import annotations
import asyncio
import os
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from shared.models import InternalEventRequest
from shared.logging import make_logger, log_event
from shared.metrics import CONTENT_TYPE, Metric, render
from .queue import TickerQueue
from .dedup import DedupCache
from .state import AggregatorState
from .router import route_event
from .transport_client import get_dispatch_worker

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
    # queue_depth is the ticker queue.  The dispatch queue is the one that
    # actually carries panel updates, so report it too — an outage that jams
    # dispatch leaves the ticker queue at 0 and is otherwise invisible here.
    worker = get_dispatch_worker()
    return {
        "queue_depth": len(snapshot),
        "dispatch_queue_depth": worker.queue_depth if worker else None,
        "dispatch_circuit": worker.circuit_state if worker else None,
        "status": "ok",
    }


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape target.

    The functional signal is dispatch_last_success_timestamp_seconds: paired
    with the transport-adapter's panel_connected gauge it asserts that panel
    updates are actually being delivered, which pod liveness cannot.
    """
    snapshot = await _queue.snapshot()
    worker = get_dispatch_worker()
    out: list[Metric] = [
        Metric(
            "housepanel_ticker_queue_depth",
            "Ticker events awaiting display.",
            "gauge",
            len(snapshot),
        ),
    ]

    if worker is not None:
        out.append(Metric(
            "housepanel_dispatch_queue_depth",
            "Commands queued for delivery to the panel.",
            "gauge",
            worker.queue_depth,
        ))
        out.append(Metric(
            "housepanel_dispatch_queue_max",
            "Capacity of the dispatch queue.",
            "gauge",
            worker.queue_max,
        ))
        for state in ("closed", "half_open", "open"):
            out.append(Metric(
                "housepanel_dispatch_circuit_state",
                "Dispatch circuit breaker state, 1 for the active state.",
                "gauge",
                1 if worker.circuit_state == state else 0,
                {"state": state},
            ))
        for outcome, total in (
            ("dispatched", worker.dispatched_total),
            ("failed", worker.failed_total),
            ("expired", worker.expired_total),
            ("rejected", worker.rejected_total),
        ):
            out.append(Metric(
                "housepanel_dispatch_commands_total",
                "Commands by delivery outcome.",
                "counter",
                total,
                {"outcome": outcome},
            ))
        if worker.last_success_wall is not None:
            # Absent rather than 0 when nothing has ever been delivered, so the
            # staleness alert cannot fire on a cold start.
            out.append(Metric(
                "housepanel_dispatch_last_success_timestamp_seconds",
                "Unix time of the last command delivered to the transport adapter.",
                "gauge",
                worker.last_success_wall,
            ))

    return Response(content=render(out), media_type=CONTENT_TYPE)


@router.post("/internal/refresh", status_code=202)
async def internal_refresh() -> JSONResponse:
    weather_url = os.environ.get("WEATHER_POLLER_URL", "http://housepanel-weather-poller:8004")
    calendar_url = os.environ.get("CALENDAR_POLLER_URL", "http://housepanel-calendar-poller:8003")

    async def _ping(url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(f"{url}/internal/poll-now")
            if resp.status_code not in (200, 202):
                log_event(logger, "refresh_ping_rejected", level="warning", url=url, status=resp.status_code)
        except Exception as exc:
            log_event(logger, "refresh_ping_failed", level="warning", url=url, error=str(exc))

    await asyncio.gather(_ping(weather_url), _ping(calendar_url))
    log_event(logger, "pollers_refreshed")
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
