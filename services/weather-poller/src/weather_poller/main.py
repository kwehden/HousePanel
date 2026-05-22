from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from shared.logging import make_logger, log_event
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
    wttr_location = os.environ.get("WTTR_LOCATION", "Portland")

    google = GoogleWeatherAdapter(api_key=google_key, location=google_location)
    owm = OpenWeatherMapAdapter(api_key=owm_key, location=owm_location)
    wttr = WttrInAdapter(location=wttr_location)

    primary_env = os.environ.get("WEATHER_PRIMARY_PROVIDER", "google").lower()
    if primary_env == "wttr_in":
        return wttr, owm
    if primary_env == "openweathermap":
        return owm, google
    return google, owm


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    aggregator_url = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
    poll_interval = int(os.environ.get("WEATHER_POLL_INTERVAL_SECONDS", "900"))

    primary, fallback = _build_adapters()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_weather,
        trigger="interval",
        seconds=poll_interval,
        args=[primary, fallback, state, aggregator_url, logger],
        id="poll_weather",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    log_event(
        logger,
        "scheduler_started",
        primary_provider=primary.provider_name,
        fallback_provider=fallback.provider_name,
        poll_interval_seconds=poll_interval,
    )

    yield

    scheduler.shutdown(wait=False)
    log_event(logger, "scheduler_stopped")


app = FastAPI(lifespan=lifespan)


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
