from __future__ import annotations

from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

import httpx

_PACIFIC = ZoneInfo("America/Los_Angeles")

from shared.models import WeatherConditions, ForecastDay
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
        humidity = data["main"].get("humidity")
        wind_speed = data.get("wind", {}).get("speed")
        today_high_c = float(data["main"].get("temp_max", temp))
        today_low_c = float(data["main"].get("temp_min", temp))

        forecast = self._fetch_forecast()

        return WeatherConditions(
            provider=self.provider_name,
            timestamp=datetime.now(timezone.utc),
            temperature_c=temp,
            conditions=conditions,
            humidity_pct=float(humidity) if humidity is not None else None,
            wind_speed_ms=float(wind_speed) if wind_speed is not None else None,
            today_high_c=today_high_c,
            today_low_c=today_low_c,
            forecast=forecast,
        )

    def _fetch_forecast(self) -> list[ForecastDay]:
        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "q": self._location,
            "appid": self._api_key,
            "units": "metric",
        }
        try:
            response = self._client.get(url, params=params)
            if response.status_code >= 300:
                return []
        except Exception:
            return []

        data = response.json()
        today = datetime.now(_PACIFIC).date()

        # Group 3-hour intervals by Pacific date; skip today
        day_data: dict[date, dict] = {}
        for item in data.get("list", []):
            item_dt = datetime.fromtimestamp(item["dt"], tz=_PACIFIC)
            d = item_dt.date()
            if d <= today:
                continue
            noon_diff = abs(item_dt.hour - 12)
            if d not in day_data:
                day_data[d] = {
                    "high": item["main"]["temp_max"],
                    "low": item["main"]["temp_min"],
                    "conditions": item["weather"][0]["description"],
                    "noon_diff": noon_diff,
                }
            else:
                day_data[d]["high"] = max(day_data[d]["high"], item["main"]["temp_max"])
                day_data[d]["low"] = min(day_data[d]["low"], item["main"]["temp_min"])
                if noon_diff < day_data[d]["noon_diff"]:
                    day_data[d]["conditions"] = item["weather"][0]["description"]
                    day_data[d]["noon_diff"] = noon_diff

        result: list[ForecastDay] = []
        for d in sorted(day_data.keys())[:4]:
            result.append(ForecastDay(
                day_label=d.strftime("%a"),
                high_c=round(day_data[d]["high"], 1),
                low_c=round(day_data[d]["low"], 1),
                conditions=day_data[d]["conditions"],
            ))
        return result
