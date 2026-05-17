from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from shared.logging import make_logger, log_event

from .client import init_ring_client, subscribe_to_doorbell_events
from .normalizer import normalize_ring_event
from .token_manager import make_token_updated_callback

logger = make_logger("ring-integration")

# ---------------------------------------------------------------------------
# Runtime state (populated during lifespan startup)
# ---------------------------------------------------------------------------
_ring = None
_listener = None
_ring_connected: bool = False
_last_event_timestamp: str | None = None


async def forward_to_aggregator(event_data: dict) -> None:
    """POST event_data to the aggregator's /internal/events endpoint."""
    aggregator_url = os.environ.get(
        "AGGREGATOR_URL", "http://housepanel-aggregator:8001"
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{aggregator_url}/internal/events", json=event_data
            )
            resp.raise_for_status()
            log_event(
                logger,
                "event_forwarded",
                event_id=event_data.get("payload", {}).get("event_id"),
            )
    except Exception as exc:  # noqa: BLE001
        log_event(
            logger,
            "event_forward_failed",
            level="error",
            error_class=type(exc).__name__,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ring, _listener, _ring_connected, _last_event_timestamp

    refresh_token = os.environ.get("RING_REFRESH_TOKEN", "")
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.setLevel(log_level)

    import asyncio

    on_token_updated = make_token_updated_callback()

    async def on_ding_handler(device: Any, ring_event: Any) -> None:
        global _last_event_timestamp
        log_event(
            logger,
            "doorbell_event_received",
            device_id=str(getattr(device, "id", "unknown")) if device else "unknown",
        )
        event_data = normalize_ring_event(device, ring_event)
        _last_event_timestamp = event_data["timestamp"]
        await forward_to_aggregator(event_data)

    def _sync_on_ding(device: Any, ring_event: Any) -> None:
        """Bridge sync ring callback to async on_ding_handler."""
        asyncio.ensure_future(on_ding_handler(device, ring_event))

    try:
        _ring = await init_ring_client(refresh_token, on_token_updated)
        _listener = await subscribe_to_doorbell_events(_ring, _sync_on_ding)
        _ring_connected = True
    except Exception as exc:  # noqa: BLE001
        log_event(
            logger,
            "ring_startup_failed",
            level="error",
            error_class=type(exc).__name__,
        )
        _ring_connected = False

    yield

    if _listener is not None:
        await _listener.stop()
    _ring_connected = False


app = FastAPI(title="HousePanel Ring Integration", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "ring_connected": _ring_connected,
        "last_event_timestamp": _last_event_timestamp,
    }
