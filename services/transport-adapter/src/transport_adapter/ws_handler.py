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


async def _read_loop(websocket: WebSocket, normal_ready: asyncio.Event | None = None,
                     panel: state.Panel | None = None) -> None:
    panel = panel if panel is not None else state.primary
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
            hostname = frame.get("hostname")
            if isinstance(hostname, str) and len(hostname) <= 63:
                panel.hostname = hostname
            await handle_hello_frame(frame, normal_ready=normal_ready, panel=panel)
        elif cmd == "OTA-START":
            panel.ota_paused = True
            log_event(logger, "ota_start_received")
            await websocket.send_text(json.dumps({"cmd": "OTA-PAUSE"}))
        elif cmd == "OTA-END":
            panel.ota_paused = False
            log_event(logger, "ota_end_received")
            await handle_post_ota_refresh(panel)


async def giga_websocket_handler(websocket: WebSocket, panel_id: str = "primary") -> None:
    panel = state.panels.get(panel_id)
    if panel is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    async with panel.websocket_handover_lock:
        previous = panel.active_websocket
        previous_task = panel.active_websocket_task
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
        discard_stale_commands(panel)
        panel.overloaded.clear()
        panel.hostname = None
        panel.ota_paused = False
        panel.giga_connected = True
        panel.active_websocket = websocket
        task = asyncio.create_task(_run_connection(websocket, panel))
        panel.active_websocket_task = task
        log_event(logger, "giga_connected", panel_id=panel_id)

    # Supersession cancels the session, not the ASGI handler. External handler
    # cancellation still propagates through gather and stops its session.
    try:
        await asyncio.gather(task, return_exceptions=True)
    finally:
        # A session cancelled before its first step cannot run its own finally.
        if panel.active_websocket_task is task:
            panel.ota_paused = False
            panel.giga_connected = False
            panel.active_websocket = None
            panel.active_websocket_task = None


class PanelBackpressure(Exception):
    pass


async def _watch_backpressure(panel: state.Panel) -> None:
    await panel.overloaded.wait()
    raise PanelBackpressure


async def _run_connection(websocket: WebSocket, panel: state.Panel) -> None:
    normal_ready = asyncio.Event()
    overloaded = False
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_read_loop(websocket, normal_ready, panel))
            tg.create_task(ws_write_loop(websocket, normal_ready, panel))
            tg.create_task(_watch_backpressure(panel))
    except* PanelBackpressure:
        overloaded = True
        log_event(logger, "panel_backpressure", level="warning", panel_id=panel.panel_id)
    except* WebSocketDisconnect:
        log_event(logger, "giga_ws_disconnected_clean")
    except* Exception as eg:
        log_event(logger, "giga_ws_error", level="warning",
                  errors=[type(e).__name__ for e in eg.exceptions])
    finally:
        # Cleanup must never clear a replacement's ownership.
        if panel.active_websocket is websocket:
            panel.ota_paused = False
            panel.giga_connected = False
            panel.active_websocket = None
            panel.active_websocket_task = None
        if overloaded:
            try:
                await asyncio.wait_for(websocket.close(code=1013), timeout=2)
            except (TimeoutError, RuntimeError, WebSocketDisconnect):
                pass
        log_event(logger, "giga_disconnected", panel_id=panel.panel_id)
