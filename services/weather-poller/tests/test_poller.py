"""Tests for poll_weather orchestration logic."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.models import WeatherConditions
from weather_poller.adapter import WeatherAPIError
from weather_poller.poller import WeatherPollerState, poll_weather


def _make_weather(provider: str = "test-provider") -> WeatherConditions:
    return WeatherConditions(
        provider=provider,
        timestamp=datetime.now(timezone.utc),
        temperature_c=20.0,
        conditions="Clear",
        humidity_pct=50.0,
        wind_speed_ms=3.0,
        icon_code=None,
    )


def _make_adapter(provider_name: str, result: WeatherConditions | Exception) -> MagicMock:
    adapter = MagicMock()
    adapter.provider_name = provider_name
    if isinstance(result, Exception):
        adapter.fetch_current.side_effect = result
    else:
        adapter.fetch_current.return_value = result
    return adapter


@pytest.mark.asyncio
async def test_poll_weather_primary_success_updates_state() -> None:
    """Primary succeeds: state updated and push called."""
    weather = _make_weather("google-weather")
    primary = _make_adapter("google-weather", weather)
    fallback = _make_adapter("openweathermap", _make_weather("openweathermap"))
    state = WeatherPollerState()
    logger = MagicMock()

    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock) as mock_push:
        await poll_weather(primary, fallback, state, "http://aggregator", logger)

    assert state.last_weather is weather
    assert state.last_provider == "google-weather"
    assert state.last_poll_timestamp is not None
    mock_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_weather_primary_fails_fallback_succeeds() -> None:
    """Primary raises WeatherAPIError: fallback called and push called."""
    primary_error = WeatherAPIError(
        provider="google-weather", http_status=503, message="Service unavailable"
    )
    fallback_weather = _make_weather("openweathermap")
    primary = _make_adapter("google-weather", primary_error)
    fallback = _make_adapter("openweathermap", fallback_weather)
    state = WeatherPollerState()
    logger = MagicMock()

    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock) as mock_push:
        await poll_weather(primary, fallback, state, "http://aggregator", logger)

    fallback.fetch_current.assert_called_once()
    assert state.last_weather is fallback_weather
    assert state.last_provider == "openweathermap"
    mock_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_weather_both_fail_state_retained() -> None:
    """Both primary and fallback raise: last_weather unchanged, push NOT called."""
    prior_weather = _make_weather("openweathermap")
    state = WeatherPollerState(
        last_weather=prior_weather,
        last_poll_timestamp=datetime.now(timezone.utc),
        last_provider="openweathermap",
    )
    primary_error = WeatherAPIError(
        provider="google-weather", http_status=500, message="Internal error"
    )
    fallback_error = WeatherAPIError(
        provider="openweathermap", http_status=401, message="Unauthorized"
    )
    primary = _make_adapter("google-weather", primary_error)
    fallback = _make_adapter("openweathermap", fallback_error)
    logger = MagicMock()

    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock) as mock_push:
        await poll_weather(primary, fallback, state, "http://aggregator", logger)

    assert state.last_weather is prior_weather
    mock_push.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TypeError("bad shape"), ValueError("bad value"), KeyError("missing"), IndexError("empty"), AttributeError("bad shape")])
async def test_invalid_primary_payload_uses_fallback(error):
    primary = _make_adapter("primary", error)
    weather = _make_weather("fallback")
    fallback = _make_adapter("fallback", weather)
    state = WeatherPollerState()
    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock):
        await poll_weather(primary, fallback, state, "http://unused", MagicMock())
    fallback.fetch_current.assert_called_once()
    assert state.last_weather is weather


@pytest.mark.asyncio
async def test_invalid_fallback_payload_records_failure():
    from weather_poller.poller import metrics
    primary = _make_adapter("primary", TypeError("bad shape"))
    fallback = _make_adapter("fallback", ValueError("bad value"))
    before = metrics.poll_failure_total
    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock) as push:
        await poll_weather(primary, fallback, WeatherPollerState(), "http://unused", MagicMock())
    assert metrics.poll_failure_total == before + 1
    push.assert_not_called()


@pytest.mark.asyncio
async def test_non_finite_primary_temperature_uses_fallback():
    bad = _make_weather("primary")
    bad.temperature_c = float("nan")
    good = _make_weather("fallback")
    state = WeatherPollerState()
    with patch("weather_poller.poller.push_weather_update", new_callable=AsyncMock):
        await poll_weather(_make_adapter("primary", bad), _make_adapter("fallback", good),
            state, "http://unused", MagicMock())
    assert state.last_weather is good
