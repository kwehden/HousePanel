from __future__ import annotations
from fastapi import FastAPI
from transport_adapter.routes import router

app = FastAPI(title="transport-adapter")
app.include_router(router)
