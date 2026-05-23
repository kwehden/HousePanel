from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from shared.logging import make_logger, log_event
from transport_adapter import state

logger = make_logger("transport-adapter")


async def ws_write_loop(websocket: WebSocket) -> None:
    while True:
        # Interrupt queue has priority — drain one item if available
        try:
            command = state.interrupt_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            await websocket.send_text(json.dumps(command))
            log_event(logger, "command_sent",
                      cmd=command.get("cmd"),
                      message_id=command.get("message_id"))
            continue

        # Normal queue is blocked during OTA
        if state.ota_paused:
            await asyncio.sleep(0.05)
            continue

        # Wait briefly for a normal-priority command
        try:
            command = await asyncio.wait_for(
                state.normal_queue.get(), timeout=0.05
            )
        except (TimeoutError, asyncio.TimeoutError):
            continue

        await websocket.send_text(json.dumps(command))
        log_event(logger, "command_sent",
                  cmd=command.get("cmd"),
                  message_id=command.get("message_id"))
