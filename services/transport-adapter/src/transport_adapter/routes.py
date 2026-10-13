from __future__ import annotations
from fastapi import APIRouter, WebSocket, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from typing import Any
from shared.contracts import validate_payload
from shared.metrics import CONTENT_TYPE, Metric, render
from transport_adapter import state
from transport_adapter.ws_handler import giga_websocket_handler
from transport_adapter.stream_decompose import decompose_command

router = APIRouter()


class CommandRequest(BaseModel):
    cmd: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{0,31}$")
    priority: int = Field(ge=0, le=99)
    payload: dict[str, Any]
    event_id: str = Field(max_length=128)


@router.post("/internal/commands", status_code=202)
async def post_command(request: CommandRequest) -> JSONResponse:
    try:
        payload = validate_payload(request.cmd.lower(), request.payload)
        items = decompose_command(request.cmd, payload)
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid or oversized command payload") from None

    queue = state.interrupt_queue if request.priority == 99 else state.normal_queue
    if queue.qsize() + len(items) > queue.maxsize:
        return JSONResponse(status_code=503, content={"error": "interrupt queue full" if request.priority == 99 else "normal queue full"})

    for item in items:
        queue.put_nowait(item)
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/internal/health")
async def internal_health() -> dict[str, str | bool | int]:
    return {
        "status": "ok",
        "giga_connected": state.giga_connected,
        "interrupt_queue_depth": state.interrupt_queue.qsize(),
        "normal_queue_depth": state.normal_queue.qsize(),
    }


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape target.

    panel_connected is what makes delivery staleness actionable: a quiet
    dispatch pipeline is expected when no panel is attached, and only
    alarming when one is.
    """
    out: list[Metric] = [
        Metric(
            "housepanel_panel_connected",
            "1 when a panel holds an open WebSocket to the transport adapter.",
            "gauge",
            1 if state.giga_connected else 0,
        ),
        Metric(
            "housepanel_panel_frames_sent_total",
            "Frames written to the panel WebSocket.",
            "counter",
            state.frames_sent_total,
        ),
        Metric(
            "housepanel_transport_queue_depth",
            "Commands awaiting write to the panel.",
            "gauge",
            state.interrupt_queue.qsize(),
            {"queue": "interrupt"},
        ),
        Metric(
            "housepanel_transport_queue_depth",
            "Commands awaiting write to the panel.",
            "gauge",
            state.normal_queue.qsize(),
            {"queue": "normal"},
        ),
    ]
    if state.last_frame_wall is not None:
        out.append(Metric(
            "housepanel_panel_last_frame_timestamp_seconds",
            "Unix time of the last frame written to the panel.",
            "gauge",
            state.last_frame_wall,
        ))
    return Response(content=render(out), media_type=CONTENT_TYPE)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws/panel")
async def ws_panel(websocket: WebSocket) -> None:
    await giga_websocket_handler(websocket)
