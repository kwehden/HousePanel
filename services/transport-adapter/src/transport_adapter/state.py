from __future__ import annotations
import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any
from fastapi import WebSocket

@dataclass
class Panel:
    panel_id: str
    interrupt_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=50))
    normal_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=50))
    giga_connected: bool = False
    ota_paused: bool = False
    active_websocket: WebSocket | None = None
    active_websocket_task: asyncio.Task[None] | None = None
    websocket_handover_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    overloaded: asyncio.Event = field(default_factory=asyncio.Event)
    frames_sent_total: int = 0
    last_frame_wall: float | None = None
    dropped_batches_total: int = 0
    normal_generation: int = 0
    normal_getter: asyncio.Task[dict[str, Any]] | None = None
    pending_normal: dict[str, Any] | None = None
    hostname: str | None = None

    @property
    def normal_depth(self) -> int:
        return self.normal_queue.qsize() + int(self.pending_normal is not None)


# Fixed identities bound queue allocation and metric cardinality. The legacy
# /ws/panel endpoint continues to select primary without a firmware update.
panels = {panel_id: Panel(panel_id) for panel_id in ("primary", "panel-2")}
primary = panels["primary"]


def connected_panels() -> list[Panel]:
    return [panel for panel in panels.values() if panel.giga_connected]

frames_sent_total: int = 0
# Wall-clock so Prometheus can compare against time(); None until the first
# frame reaches the panel.
last_frame_wall: float | None = None


def record_frame_sent(panel: Panel | None = None) -> None:
    global frames_sent_total, last_frame_wall
    frames_sent_total += 1
    last_frame_wall = time.time()
    panel = panel if panel is not None else primary
    panel.frames_sent_total += 1
    panel.last_frame_wall = last_frame_wall

AGGREGATOR_URL: str = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
TRANSPORT_ADAPTER_PORT: int = int(os.environ.get("TRANSPORT_ADAPTER_PORT", "8002"))
