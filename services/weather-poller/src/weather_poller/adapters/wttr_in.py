from __future__ import annotations

from datetime import datetime, timezone

import httpx

from shared.models import WeatherConditions, ForecastDay
from weather_poller.adapter import WeatherAPIError


def _midday_conditions(hourly: list[dict]) -> str:
    for slot in hourly:
        if slot.get("time") == "1200":
            return slot["weatherDesc"][0]["value"].lower()
    if hourly:
        return hourly[0]["weatherDesc"][0]["value"].lower()
    return "unknown"


class WttrInAdapter:
    provider_name = "wttr_in"

    def __init__(self, location: str) -> None:
        self._location = location
        self._client = httpx.Client(timeout=10)

    def fetch_current(self) -> WeatherConditions:
        url = f"https://wttr.in/{self._location}"
        response = self._client.get(url, params={"format": "j1"})
        if response.status_code >= 300:
            raise WeatherAPIError(
                provider=self.provider_name,
                http_status=response.status_code,
                message=response.text[:200],
            )
        try:
            data = response.json()
            cur = data["current_condition"][0]
            temp_c = float(cur["temp_C"])
            conditions = cur["weatherDesc"][0]["value"].lower()
            humidity = float(cur["humidity"])
            wind_ms = float(cur["windspeedKmph"]) / 3.6

            today_data = data["weather"][0]
            today_high = float(today_data["maxtempC"])
            today_low = float(today_data["mintempC"])

            forecast: list[ForecastDay] = []
            for day_data in data["weather"][1:3]:
                d = datetime.strptime(day_data["date"], "%Y-%m-%d")
                forecast.append(ForecastDay(
                    day_label=d.strftime("%a"),
                    high_c=float(day_data["maxtempC"]),
                    low_c=float(day_data["mintempC"]),
                    conditions=_midday_conditions(day_data.get("hourly", [])),
                ))
        except (KeyError, IndexError, ValueError) as exc:
            raise WeatherAPIError(
                provider=self.provider_name,
                http_status=200,
                message=f"Unexpected response structure: {exc}",
            ) from exc

        return WeatherConditions(
            provider=self.provider_name,
            timestamp=datetime.now(timezone.utc),
            temperature_c=temp_c,
            conditions=conditions,
            humidity_pct=humidity,
            wind_speed_ms=round(wind_ms, 1),
            today_high_c=today_high,
            today_low_c=today_low,
            forecast=forecast,
        )
