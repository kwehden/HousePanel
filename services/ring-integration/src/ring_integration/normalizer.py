from __future__ import annotations

import uuid
from datetime import datetime, timezone


def normalize_ring_event(device, ding_event=None) -> dict:
    """Return a dict matching POST /internal/events for a doorbell ding."""
    return {
        "source": "ring",
        "event_type": "doorbell-interrupt",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "priority": 99,
        "payload": {
            "device_id": str(getattr(device, "id", "unknown")),
            "device_name": str(getattr(device, "name", "doorbell")),
            "event_id": str(uuid.uuid4()),
        },
    }
