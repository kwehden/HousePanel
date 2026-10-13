from __future__ import annotations
from fastapi import FastAPI
from shared.body_limit import BodyLimitMiddleware
from fastapi.responses import Response
from shared.metrics import CONTENT_TYPE, render
from .forwarder import metrics as source_metrics
from .routes import router

app = FastAPI(title="HousePanel Webhook Receiver")
app.add_middleware(BodyLimitMiddleware)
app.include_router(router)


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=render(source_metrics.render()), media_type=CONTENT_TYPE)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
