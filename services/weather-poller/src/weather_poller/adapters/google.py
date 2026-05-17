from __future__ import annotations

from datetime import datetime, timezone

import httpx

from shared.models import WeatherConditions
from weather_poller.adapter import WeatherAPIError


class GoogleWeatherAdapter:
    provider_name = "google-weather"

    def __init__(self, api_key: str, location: str) -> None:
        self._api_key = api_key
        self._location = location
        lat_str, lon_str = location.split(",", 1)
        self._lat = lat_str.strip()
        self._lon = lon_str.strip()
        self._client = httpx.Client(timeout=10)

    def fetch_current(self) -> WeatherConditions:
        url = "https://weather.googleapis.com/v1/currentConditions:lookup"
        params = {
            "key": self._api_key,
            "location.latitude": self._lat,
            "location.longitude": self._lon,
        }
        response = self._client.get(url, params=params)
        if response.status_code >= 300:
            raise WeatherAPIError(
                provider=self.provider_name,
                http_status=response.status_code,
                message=response.text,
            )
        data = response.json()
        cc = data["currentConditions"]
        temp = float(cc["temperature"]["degrees"])
        humidity = cc.get("humidity")
        wind_block = cc.get("wind", {})
        wind_speed = wind_block.get("speed", {}).get("value") if wind_block else None
        weather_cond = cc.get("weatherCondition", {})
        conditions_text = (
            weather_cond.get("description", {}).get("text", "")
            if weather_cond
            else ""
        )
        icon_base_uri = weather_cond.get("iconBaseUri") if weather_cond else None
        return WeatherConditions(
            provider=self.provider_name,
            timestamp=datetime.now(timezone.utc),
            temperature_c=temp,
            conditions=conditions_text,
            humidity_pct=float(humidity) if humidity is not None else None,
            wind_speed_ms=float(wind_speed) if wind_speed is not None else None,
            icon_code=icon_base_uri,
        )
