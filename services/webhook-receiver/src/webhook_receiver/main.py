from __future__ import annotations
from fastapi import FastAPI
from .routes import router

app = FastAPI(title="HousePanel Webhook Receiver")
app.include_router(router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
