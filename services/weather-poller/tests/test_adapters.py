"""Tests for Google and OpenWeatherMap adapters using mocked httpx.Client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from weather_poller.adapter import WeatherAPIError
from weather_poller.adapters.google import GoogleWeatherAdapter
from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter


def _mock_response(status_code: int, body: dict | str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.text = body
        resp.json.return_value = {}
    return resp


GOOGLE_VALID_RESPONSE = {
    "currentConditions": {
        "temperature": {"degrees": 18.5, "unit": "CELSIUS"},
        "humidity": 65,
        "wind": {"speed": {"value": 3.2, "unit": "METERS_PER_SECOND"}},
        "weatherCondition": {
            "description": {"text": "Partly cloudy"},
            "iconBaseUri": "https://maps.gstatic.com/weather/v1/cloudy",
        },
    }
}

OWM_VALID_RESPONSE = {
    "main": {"temp": 22.3, "humidity": 70},
    "weather": [{"description": "light rain", "icon": "10d"}],
    "wind": {"speed": 5.1},
}


class TestGoogleWeatherAdapter:
    def test_fetch_current_valid_response(self) -> None:
        adapter = GoogleWeatherAdapter(api_key="test-key", location="37.7749,-122.4194")
        mock_resp = _mock_response(200, GOOGLE_VALID_RESPONSE)

        with patch.object(adapter._client, "get", return_value=mock_resp):
            result = adapter.fetch_current()

        assert result.provider == "google-weather"
        assert result.temperature_c == 18.5
        assert result.conditions == "Partly cloudy"
        assert result.humidity_pct == 65.0
        assert result.wind_speed_ms == 3.2
        assert result.icon_code == "https://maps.gstatic.com/weather/v1/cloudy"

    def test_fetch_current_4xx_raises_weather_api_error(self) -> None:
        adapter = GoogleWeatherAdapter(api_key="bad-key", location="0.0,0.0")
        mock_resp = _mock_response(403, "Forbidden")

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        err = exc_info.value
        assert err.provider == "google-weather"
        assert err.http_status == 403

    def test_fetch_current_5xx_raises_weather_api_error(self) -> None:
        adapter = GoogleWeatherAdapter(api_key="key", location="51.5074,-0.1278")
        mock_resp = _mock_response(503, "Service Unavailable")

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        assert exc_info.value.http_status == 503


class TestOpenWeatherMapAdapter:
    def test_fetch_current_valid_response(self) -> None:
        adapter = OpenWeatherMapAdapter(api_key="test-key", location="San Francisco")
        mock_resp = _mock_response(200, OWM_VALID_RESPONSE)

        with patch.object(adapter._client, "get", return_value=mock_resp):
            result = adapter.fetch_current()

        assert result.provider == "openweathermap"
        assert result.temperature_c == 22.3
        assert result.conditions == "light rain"
        assert result.humidity_pct == 70.0
        assert result.wind_speed_ms == 5.1

    def test_fetch_current_4xx_raises_weather_api_error(self) -> None:
        adapter = OpenWeatherMapAdapter(api_key="bad-key", location="London")
        mock_resp = _mock_response(401, "Unauthorized")

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        err = exc_info.value
        assert err.provider == "openweathermap"
        assert err.http_status == 401

    def test_fetch_current_5xx_raises_weather_api_error(self) -> None:
        adapter = OpenWeatherMapAdapter(api_key="key", location="Paris")
        mock_resp = _mock_response(500, "Internal Server Error")

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        assert exc_info.value.http_status == 500
