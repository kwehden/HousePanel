from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from shared.logging import make_logger, log_event
from transport_adapter import state
from transport_adapter.ws_write_loop import ws_write_loop
from transport_adapter.state_refresh import discard_stale_commands, handle_hello_frame, handle_post_ota_refresh

logger = make_logger("transport-adapter")


async def _read_loop(websocket: WebSocket) -> None:
    while True:
        raw = await websocket.receive_text()
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(frame, dict):
            continue
        cmd = frame.get("cmd")
        if cmd == "HELLO":
            await handle_hello_frame(frame)
        elif cmd == "OTA-START":
            state.ota_paused = True
            log_event(logger, "ota_start_received")
            await websocket.send_text(json.dumps({"cmd": "OTA-PAUSE"}))
        elif cmd == "OTA-END":
            state.ota_paused = False
            log_event(logger, "ota_end_received")
            await handle_post_ota_refresh()


async def giga_websocket_handler(websocket: WebSocket) -> None:
    await websocket.accept()
    async with state.websocket_handover_lock:
        previous = state.active_websocket
        previous_task = state.active_websocket_task
        # Stop both queue consumers and refresh producers before the new HELLO.
        # Closing a socket alone does not terminate its pending receive/get calls.
        if previous_task is not None:
            previous_task.cancel()
            await asyncio.gather(previous_task, return_exceptions=True)
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=1012)
            except (RuntimeError, WebSocketDisconnect):
                pass
        # The replacement can wait before HELLO; do not send the old OTA backlog.
        discard_stale_commands()
        state.ota_paused = False
        state.giga_connected = True
        state.active_websocket = websocket
        task = asyncio.create_task(_run_connection(websocket))
        state.active_websocket_task = task
        log_event(logger, "giga_connected")

    # Supersession cancels the session, not the ASGI handler. External handler
    # cancellation still propagates through gather and stops its session.
    try:
        await asyncio.gather(task, return_exceptions=True)
    finally:
        # A session cancelled before its first step cannot run its own finally.
        if state.active_websocket_task is task:
            state.ota_paused = False
            state.giga_connected = False
            state.active_websocket = None
            state.active_websocket_task = None


async def _run_connection(websocket: WebSocket) -> None:
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_read_loop(websocket))
            tg.create_task(ws_write_loop(websocket))
    except* WebSocketDisconnect:
        log_event(logger, "giga_ws_disconnected_clean")
    except* Exception as eg:
        log_event(logger, "giga_ws_error", level="warning",
                  errors=[type(e).__name__ for e in eg.exceptions])
    finally:
        # Cleanup must never clear a replacement's ownership.
        if state.active_websocket is websocket:
            state.ota_paused = False
            state.giga_connected = False
            state.active_websocket = None
            state.active_websocket_task = None
        log_event(logger, "giga_disconnected")
