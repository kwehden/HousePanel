from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from shared.logging import make_logger, log_event
from transport_adapter import state
from transport_adapter.stream_decompose import encode_frame

logger = make_logger("transport-adapter")


async def ws_write_loop(websocket: WebSocket, normal_ready: asyncio.Event | None = None,
                        panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
    while True:
        # Interrupt queue has priority — drain one item if available
        try:
            command = panel.interrupt_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        else:
            await websocket.send_text(encode_frame(command))
            state.record_frame_sent(panel)
            log_event(logger, "command_sent",
                      cmd=command.get("cmd"),
                      message_id=command.get("message_id"))
            continue

        # A session must receive HELLO before consuming normal commands.
        if panel.ota_paused or (normal_ready is not None and not normal_ready.is_set()):
            await asyncio.sleep(0.05)
            continue

        if panel.pending_normal is None:
            # HELLO/OTA-END can invalidate a pending get without cancelling the
            # writer. Keep ownership explicit so no old waiter steals replay.
            generation = panel.normal_generation
            getter = asyncio.create_task(panel.normal_queue.get())
            panel.normal_getter = getter
            try:
                command = await asyncio.wait_for(getter, timeout=0.05)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                owner = asyncio.current_task()
                if owner is not None and owner.cancelling():
                    raise
                continue
            finally:
                if panel.normal_getter is getter:
                    panel.normal_getter = None
            if generation == panel.normal_generation:
                panel.pending_normal = command
            # Recheck OTA, HELLO readiness, and interrupt priority after await.
            continue
        command = panel.pending_normal
        panel.pending_normal = None
        await websocket.send_text(encode_frame(command))
        state.record_frame_sent(panel)
        log_event(logger, "command_sent",
                  cmd=command.get("cmd"),
                  message_id=command.get("message_id"))
