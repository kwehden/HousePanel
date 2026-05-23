from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from shared.logging import make_logger, log_event
from transport_adapter import state
from transport_adapter.ws_write_loop import ws_write_loop
from transport_adapter.state_refresh import handle_hello_frame, handle_post_ota_refresh

logger = make_logger("transport-adapter")


async def _read_loop(websocket: WebSocket) -> None:
    while True:
        raw = await websocket.receive_text()
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
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
    state.giga_connected = True
    state.active_websocket = websocket
    log_event(logger, "giga_connected")

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
        state.giga_connected = False
        state.active_websocket = None
        log_event(logger, "giga_disconnected")
