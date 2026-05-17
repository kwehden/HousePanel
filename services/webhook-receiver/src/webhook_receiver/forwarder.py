from __future__ import annotations
import os
import httpx
from shared.logging import make_logger, log_event

logger = make_logger("webhook-receiver")


async def forward_to_aggregator(event_data: dict) -> None:
    aggregator_url = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{aggregator_url}/internal/events", json=event_data)
            resp.raise_for_status()
            log_event(logger, "event_forwarded", http_status=resp.status_code)
    except Exception as exc:
        log_event(logger, "event_forward_failed", level="error", error=str(exc))
