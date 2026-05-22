"""Tests for Google, OpenWeatherMap, and wttr.in adapters using mocked httpx.Client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from weather_poller.adapter import WeatherAPIError
from weather_poller.adapters.google import GoogleWeatherAdapter
from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter
from weather_poller.adapters.wttr_in import WttrInAdapter


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


WTTR_VALID_RESPONSE = {
    "current_condition": [{
        "temp_C": "14",
        "humidity": "78",
        "windspeedKmph": "18",
        "weatherDesc": [{"value": "Partly cloudy"}],
    }],
    "weather": [
        {
            "date": "2026-05-22",
            "maxtempC": "17",
            "mintempC": "9",
            "hourly": [
                {"time": "0",    "weatherDesc": [{"value": "Cloudy"}]},
                {"time": "1200", "weatherDesc": [{"value": "Partly cloudy"}]},
            ],
        },
        {
            "date": "2026-05-23",
            "maxtempC": "19",
            "mintempC": "11",
            "hourly": [{"time": "1200", "weatherDesc": [{"value": "Sunny"}]}],
        },
        {
            "date": "2026-05-24",
            "maxtempC": "16",
            "mintempC": "8",
            "hourly": [{"time": "1200", "weatherDesc": [{"value": "Light rain"}]}],
        },
    ],
}


class TestWttrInAdapter:
    def test_fetch_current_valid_response(self) -> None:
        adapter = WttrInAdapter(location="Seattle")
        mock_resp = _mock_response(200, WTTR_VALID_RESPONSE)

        with patch.object(adapter._client, "get", return_value=mock_resp):
            result = adapter.fetch_current()

        assert result.provider == "wttr_in"
        assert result.temperature_c == 14.0
        assert result.conditions == "partly cloudy"
        assert result.humidity_pct == 78.0
        assert round(result.wind_speed_ms, 1) == round(18 / 3.6, 1)
        assert result.today_high_c == 17.0
        assert result.today_low_c == 9.0
        assert len(result.forecast) == 2
        assert result.forecast[0].day_label == "Sat"
        assert result.forecast[0].high_c == 19.0
        assert result.forecast[0].conditions == "sunny"
        assert result.forecast[1].day_label == "Sun"
        assert result.forecast[1].conditions == "light rain"

    def test_fetch_current_4xx_raises_weather_api_error(self) -> None:
        adapter = WttrInAdapter(location="Seattle")
        mock_resp = _mock_response(404, "Not Found")

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        err = exc_info.value
        assert err.provider == "wttr_in"
        assert err.http_status == 404

    def test_fetch_current_malformed_response_raises_weather_api_error(self) -> None:
        """A structurally unexpected response raises WeatherAPIError, not KeyError."""
        adapter = WttrInAdapter(location="Seattle")
        mock_resp = _mock_response(200, {"current_condition": []})  # empty list → IndexError

        with patch.object(adapter._client, "get", return_value=mock_resp):
            with pytest.raises(WeatherAPIError) as exc_info:
                adapter.fetch_current()

        err = exc_info.value
        assert err.provider == "wttr_in"
        assert err.http_status == 200
        assert "Unexpected response structure" in str(err)
