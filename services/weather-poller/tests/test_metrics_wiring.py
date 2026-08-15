"""The recorder must be driven by the real poll/push paths, not just exist."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.models import WeatherConditions
from weather_poller.adapter import WeatherAPIError
from weather_poller.poller import (
    WeatherPollerState,
    metrics,
    poll_weather,
    push_weather_update,
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.poll_success_total = 0
    metrics.poll_failure_total = 0
    metrics.push_success_total = 0
    metrics.push_failure_total = 0
    metrics.last_poll_success_wall = None
    metrics.last_push_success_wall = None
    yield


def _weather() -> WeatherConditions:
    return WeatherConditions(
        provider="test", timestamp=datetime.now(timezone.utc), temperature_c=20.0,
        conditions="Clear", humidity_pct=50.0, wind_speed_ms=3.0, icon_code=None,
    )


def _client(*, raises: Exception | None = None) -> MagicMock:
    client = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=raises)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_successful_push_advances_the_push_timestamp():
    with patch("weather_poller.poller.httpx.AsyncClient", return_value=_client()):
        await push_weather_update(_weather(), "http://agg", MagicMock())

    assert metrics.push_success_total == 1
    assert metrics.last_push_success_wall is not None


@pytest.mark.asyncio
async def test_failed_push_is_counted_and_leaves_the_timestamp_unset():
    """The push swallows its exception, so only the metric records the failure."""
    client = _client(raises=RuntimeError("aggregator down"))
    with patch("weather_poller.poller.httpx.AsyncClient", return_value=client):
        await push_weather_update(_weather(), "http://agg", MagicMock())

    assert metrics.push_failure_total == 1
    assert metrics.last_push_success_wall is None


@pytest.mark.asyncio
async def test_poll_success_recorded_and_push_attempted():
    primary = MagicMock()
    primary.provider_name = "google"
    primary.fetch_current.return_value = _weather()

    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock):
        await poll_weather(primary, MagicMock(), WeatherPollerState(), "http://agg", MagicMock())

    assert metrics.poll_success_total == 1
    assert metrics.last_poll_success_wall is not None


@pytest.mark.asyncio
async def test_both_providers_failing_records_a_poll_failure():
    err = WeatherAPIError(provider="p", http_status=500, message="boom")
    primary = MagicMock(); primary.provider_name = "google"
    primary.fetch_current.side_effect = err
    fallback = MagicMock(); fallback.provider_name = "owm"
    fallback.fetch_current.side_effect = err

    await poll_weather(primary, fallback, WeatherPollerState(), "http://agg", MagicMock())

    assert metrics.poll_failure_total == 1
    assert metrics.poll_success_total == 0


@pytest.mark.asyncio
async def test_fallback_success_counts_as_a_poll_success():
    """A fallback that works is a working poller, not a degraded one."""
    primary = MagicMock(); primary.provider_name = "google"
    primary.fetch_current.side_effect = WeatherAPIError(
        provider="google", http_status=500, message="boom")
    fallback = MagicMock(); fallback.provider_name = "owm"
    fallback.fetch_current.return_value = _weather()

    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock):
        await poll_weather(primary, fallback, WeatherPollerState(), "http://agg", MagicMock())

    assert metrics.poll_success_total == 1
    assert metrics.poll_failure_total == 0
