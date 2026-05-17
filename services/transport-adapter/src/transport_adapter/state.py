from __future__ import annotations
import asyncio
import os

interrupt_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
normal_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
giga_connected: bool = False
ota_paused: bool = False
active_websocket = None  # set on connect, cleared on disconnect

AGGREGATOR_URL: str = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
TRANSPORT_ADAPTER_PORT: int = int(os.environ.get("TRANSPORT_ADAPTER_PORT", "8002"))
