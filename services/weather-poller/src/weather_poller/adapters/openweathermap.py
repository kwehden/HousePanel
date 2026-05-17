from __future__ import annotations

from datetime import datetime, timezone

import httpx

from shared.models import WeatherConditions
from weather_poller.adapter import WeatherAPIError


class OpenWeatherMapAdapter:
    provider_name = "openweathermap"

    def __init__(self, api_key: str, location: str) -> None:
        self._api_key = api_key
        self._location = location
        self._client = httpx.Client(timeout=10)

    def fetch_current(self) -> WeatherConditions:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": self._location,
            "appid": self._api_key,
            "units": "metric",
        }
        response = self._client.get(url, params=params)
        if response.status_code >= 300:
            raise WeatherAPIError(
                provider=self.provider_name,
                http_status=response.status_code,
                message=response.text,
            )
        data = response.json()
        temp = float(data["main"]["temp"])
        conditions = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind_speed = data.get("wind", {}).get("speed")
        return WeatherConditions(
            provider=self.provider_name,
            timestamp=datetime.now(timezone.utc),
            temperature_c=temp,
            conditions=conditions,
            humidity_pct=float(humidity) if humidity is not None else None,
            wind_speed_ms=float(wind_speed) if wind_speed is not None else None,
            icon_code=None,
        )
