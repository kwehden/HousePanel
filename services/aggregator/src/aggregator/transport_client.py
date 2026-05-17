from __future__ import annotations
import os
import httpx
from shared.logging import make_logger, log_event

logger = make_logger("aggregator")


async def dispatch_command_to_transport(
    cmd: str, priority: int, payload: dict, event_id: str
) -> None:
    transport_url = os.environ.get("TRANSPORT_ADAPTER_URL", "http://housepanel-transport-adapter:8002")
    body = {"cmd": cmd, "priority": priority, "payload": payload, "event_id": event_id}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{transport_url}/internal/commands", json=body)
            resp.raise_for_status()
            log_event(logger, "command_dispatched", cmd=cmd, event_id=event_id)
    except Exception as exc:
        log_event(logger, "command_dispatch_failed", level="error", cmd=cmd, event_id=event_id, error=str(exc))
