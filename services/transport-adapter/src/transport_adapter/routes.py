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

    targets = state.connected_panels() or [state.primary]
    accepted = 0
    for panel in targets:
        queue = panel.interrupt_queue if request.priority == 99 else panel.normal_queue
        if queue.qsize() + len(items) > queue.maxsize:
            panel.dropped_batches_total += 1
            # A slow peer must not stall delivery to the other panel. It will
            # reconnect and replay a snapshot. OTA-END already replays state.
            if panel.giga_connected and not panel.ota_paused:
                panel.overloaded.set()
            continue
        for item in items:
            queue.put_nowait(item)
        accepted += 1
    if not accepted:
        return JSONResponse(status_code=503, content={"error": "interrupt queue full" if request.priority == 99 else "normal queue full"})
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/internal/health")
async def internal_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "giga_connected": bool(state.connected_panels()),
        "interrupt_queue_depth": sum(p.interrupt_queue.qsize() for p in state.panels.values()),
        "normal_queue_depth": sum(p.normal_depth for p in state.panels.values()),
        "panels": {p.panel_id: {
            "connected": p.giga_connected,
            "hostname": p.hostname,
            "ota_paused": p.ota_paused,
            "normal_queue_depth": p.normal_depth,
            "interrupt_queue_depth": p.interrupt_queue.qsize(),
            "frames_sent_total": p.frames_sent_total,
        } for p in state.panels.values()},
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
            1 if state.connected_panels() else 0,
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
            sum(p.interrupt_queue.qsize() for p in state.panels.values()),
            {"queue": "interrupt"},
        ),
        Metric(
            "housepanel_transport_queue_depth",
            "Commands awaiting write to the panel.",
            "gauge",
            sum(p.normal_depth for p in state.panels.values()),
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
    for panel in state.panels.values():
        labels = {"panel_id": panel.panel_id}
        out.extend([
            Metric("housepanel_panel_session_connected", "Named panel WebSocket connected.",
                   "gauge", int(panel.giga_connected), labels),
            Metric("housepanel_panel_session_ota_paused", "Named panel normal updates intentionally paused for OTA.",
                   "gauge", int(panel.ota_paused), labels),
            Metric("housepanel_panel_session_frames_sent_total", "Frames written to this panel.",
                   "counter", panel.frames_sent_total, labels),
            Metric("housepanel_panel_dropped_batches_total", "Batches rejected for this panel at capacity.",
                   "counter", panel.dropped_batches_total, labels),
            Metric("housepanel_panel_session_queue_depth", "Frames awaiting write to this panel.",
                   "gauge", panel.normal_depth, {**labels, "queue": "normal"}),
            Metric("housepanel_panel_session_queue_depth", "Frames awaiting write to this panel.",
                   "gauge", panel.interrupt_queue.qsize(), {**labels, "queue": "interrupt"}),
        ])
        if panel.last_frame_wall is not None:
            out.append(Metric("housepanel_panel_session_last_frame_timestamp_seconds",
                              "Last frame written to this panel.", "gauge", panel.last_frame_wall, labels))
    return Response(content=render(out), media_type=CONTENT_TYPE)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws/panel")
async def ws_panel(websocket: WebSocket) -> None:
    await giga_websocket_handler(websocket)


@router.websocket("/ws/panels/{panel_id}")
async def ws_named_panel(websocket: WebSocket, panel_id: str) -> None:
    await giga_websocket_handler(websocket, panel_id=panel_id)
