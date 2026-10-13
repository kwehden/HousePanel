from __future__ import annotations
import asyncio
import os
import time
from typing import Any
from fastapi import WebSocket

interrupt_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
normal_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
giga_connected: bool = False
ota_paused: bool = False
active_websocket: WebSocket | None = None
active_websocket_task: asyncio.Task[None] | None = None
websocket_handover_lock = asyncio.Lock()

frames_sent_total: int = 0
# Wall-clock so Prometheus can compare against time(); None until the first
# frame reaches the panel.
last_frame_wall: float | None = None


def record_frame_sent() -> None:
    global frames_sent_total, last_frame_wall
    frames_sent_total += 1
    last_frame_wall = time.time()

AGGREGATOR_URL: str = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
TRANSPORT_ADAPTER_PORT: int = int(os.environ.get("TRANSPORT_ADAPTER_PORT", "8002"))
