from __future__ import annotations
from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from transport_adapter import state
from transport_adapter.ws_handler import giga_websocket_handler
from transport_adapter.stream_decompose import decompose_command

router = APIRouter()


class CommandRequest(BaseModel):
    cmd: str
    priority: int
    payload: dict
    event_id: str


@router.post("/internal/commands", status_code=202)
async def post_command(request: CommandRequest) -> JSONResponse:
    items = decompose_command(request.cmd, request.payload)

    if request.priority == 99:
        for item in items:
            state.interrupt_queue.put_nowait(item)
        return JSONResponse(status_code=202, content={"accepted": True})

    if state.normal_queue.qsize() + len(items) > state.normal_queue.maxsize:
        return JSONResponse(status_code=503, content={"error": "normal queue full"})

    for item in items:
        state.normal_queue.put_nowait(item)
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/internal/health")
async def internal_health() -> dict:
    return {
        "status": "ok",
        "giga_connected": state.giga_connected,
        "interrupt_queue_depth": state.interrupt_queue.qsize(),
        "normal_queue_depth": state.normal_queue.qsize(),
    }


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.websocket("/ws/panel")
async def ws_panel(websocket: WebSocket) -> None:
    await giga_websocket_handler(websocket)
