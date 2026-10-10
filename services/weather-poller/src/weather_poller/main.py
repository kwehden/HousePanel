from __future__ import annotations

import os
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import httpx

from fastapi.responses import Response

from shared.logging import make_logger, log_event
from shared.metrics import CONTENT_TYPE, render
from shared.polling import PollRunner
from weather_poller.poller import metrics as source_metrics
from weather_poller.adapter import WeatherAdapter
from weather_poller.adapters.google import GoogleWeatherAdapter
from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter
from weather_poller.adapters.wttr_in import WttrInAdapter
from weather_poller.poller import WeatherPollerState, poll_weather

logger = make_logger("weather-poller")
state = WeatherPollerState()


def _build_adapters() -> tuple[WeatherAdapter, WeatherAdapter]:
    google_key = os.environ.get("GOOGLE_WEATHER_API_KEY", "")
    google_location = os.environ.get("GOOGLE_WEATHER_LOCATION", "0,0")
    owm_key = os.environ.get("OPENWEATHERMAP_API_KEY", "")
    owm_location = os.environ.get("OPENWEATHERMAP_LOCATION", "London")
    primary_env = os.environ.get("WEATHER_PRIMARY_PROVIDER", "google").lower()
    owm = OpenWeatherMapAdapter(api_key=owm_key, location=owm_location)
    if primary_env == "wttr_in":
        return WttrInAdapter(location=os.environ.get("WTTR_LOCATION", "")), owm
    google = GoogleWeatherAdapter(api_key=google_key, location=google_location)
    if primary_env == "openweathermap":
        return owm, google
    return google, owm


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    aggregator_url = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
    poll_interval = int(os.environ.get("WEATHER_POLL_INTERVAL_SECONDS", "900"))

    with ExitStack() as stack:
        primary, fallback = _build_adapters()
        stack.callback(primary.close)
        stack.callback(fallback.close)
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            source_metrics.poll_interval_seconds = poll_interval
            runner = PollRunner(
                lambda: poll_weather(
                    primary, fallback, state, aggregator_url, logger, http_client
                ), logger,
            )
            scheduler = AsyncIOScheduler()
            scheduler.add_job(
                runner.run,
                trigger="interval",
                seconds=poll_interval,
                id="poll_weather",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )
            scheduler.add_job(
                runner.run,
                trigger="cron",
                hour=0,
                minute=5,
                timezone="America/Los_Angeles",
                id="poll_weather_midnight",
                replace_existing=True,
            )
            app.state.poll_runner = runner
            scheduler.start()
            log_event(
                logger,
                "scheduler_started",
                primary_provider=primary.provider_name,
                fallback_provider=fallback.provider_name,
                poll_interval_seconds=poll_interval,
            )
            try:
                yield
            finally:
                scheduler.shutdown(wait=False)
                await runner.close()
                log_event(logger, "scheduler_stopped")


app = FastAPI(lifespan=lifespan)


@app.post("/internal/poll-now", status_code=202)
async def poll_now() -> dict:
    app.state.poll_runner.request()
    return {"accepted": True}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=render(source_metrics.render()), media_type=CONTENT_TYPE)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "last_poll_timestamp": (
            state.last_poll_timestamp.isoformat()
            if state.last_poll_timestamp is not None
            else None
        ),
        "last_provider": state.last_provider,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("weather_poller.main:app", host="0.0.0.0", port=8004)
