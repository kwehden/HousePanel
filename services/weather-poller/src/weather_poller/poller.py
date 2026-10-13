from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from shared.models import WeatherConditions
from shared.logging import log_event
from shared.metrics import SourceMetrics
from shared.contracts import JsonObject, validate_payload
from weather_poller.adapter import WeatherAdapter, WeatherAPIError

# Interval is overwritten from config at startup; the default matches main.py.
metrics = SourceMetrics("weather", poll_interval_seconds=900)


@dataclass
class WeatherPollerState:
    last_weather: WeatherConditions | None = None
    last_poll_timestamp: datetime | None = None
    last_provider: str | None = None


def _weather_as_dict(weather: WeatherConditions) -> JsonObject:
    """Convert WeatherConditions to a JSON-serializable dict."""
    d = dataclasses.asdict(weather)
    if isinstance(d.get("timestamp"), datetime):
        d["timestamp"] = d["timestamp"].isoformat()
    return d


async def push_weather_update(
    weather: WeatherConditions,
    aggregator_url: str,
    logger: logging.Logger,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    body = {
        "source": "weather-poller",
        "event_type": "weather-update",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "priority": 10,
        "payload": _weather_as_dict(weather),
    }
    try:
        async with (nullcontext(http_client) if http_client is not None
                    else httpx.AsyncClient(timeout=5)) as client:
            response = await client.post(
                f"{aggregator_url}/internal/events", json=body
            )
            response.raise_for_status()
        metrics.record_push(True)
    except Exception as exc:
        metrics.record_push(False)
        log_event(
            logger,
            "push_weather_update_failed",
            level="error",
            error=str(exc),
        )


async def poll_weather(
    primary: WeatherAdapter,
    fallback: WeatherAdapter,
    state: WeatherPollerState,
    aggregator_url: str,
    logger: logging.Logger,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    log_event(logger, "poll_started", provider=primary.provider_name)
    start_ms = time.monotonic() * 1000
    weather: WeatherConditions | None = None

    try:
        weather = await asyncio.to_thread(primary.fetch_current)
        validate_payload("weather-update", _weather_as_dict(weather))
    except (WeatherAPIError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        log_event(
            logger,
            "poll_error",
            level="error",
            provider=primary.provider_name,
            http_status=exc.http_status if isinstance(exc, WeatherAPIError) else 200,
            error_message=exc.message if isinstance(exc, WeatherAPIError) else "Invalid upstream payload",
            error_type=type(exc).__name__,
        )
        log_event(logger, "fallback_triggered", fallback_provider=fallback.provider_name)
        try:
            weather = await asyncio.to_thread(fallback.fetch_current)
            validate_payload("weather-update", _weather_as_dict(weather))
        except (WeatherAPIError, ValueError, TypeError, KeyError, IndexError, AttributeError) as fb_exc:
            metrics.record_poll(False)
            log_event(
                logger,
                "poll_error",
                level="error",
                provider=fallback.provider_name,
                http_status=fb_exc.http_status if isinstance(fb_exc, WeatherAPIError) else 200,
                error_message=fb_exc.message if isinstance(fb_exc, WeatherAPIError) else "Invalid upstream payload",
                error_type=type(fb_exc).__name__,
            )
            return

    if weather is not None:
        metrics.record_poll(True)
        state.last_weather = weather
        state.last_poll_timestamp = datetime.now(timezone.utc)
        state.last_provider = weather.provider
        duration_ms = time.monotonic() * 1000 - start_ms
        log_event(
            logger,
            "poll_success",
            provider=weather.provider,
            poll_duration_ms=round(duration_ms, 2),
        )
        await push_weather_update(weather, aggregator_url, logger, http_client)
