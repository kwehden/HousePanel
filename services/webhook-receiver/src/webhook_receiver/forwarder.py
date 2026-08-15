from __future__ import annotations
import os
import httpx
from shared.logging import make_logger, log_event
from shared.metrics import SourceMetrics

logger = make_logger("webhook-receiver")

# No poll interval: webhooks are event-driven, so silence is normal and a
# staleness alert would be pure noise.
metrics = SourceMetrics("webhook")


async def forward_to_aggregator(event_data: dict) -> None:
    aggregator_url = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{aggregator_url}/internal/events", json=event_data)
            resp.raise_for_status()
            log_event(logger, "event_forwarded", http_status=resp.status_code)
        metrics.record_push(True)
    except Exception as exc:
        metrics.record_push(False)
        log_event(logger, "event_forward_failed", level="error", error=str(exc))
