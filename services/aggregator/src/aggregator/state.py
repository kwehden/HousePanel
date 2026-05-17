from __future__ import annotations
from dataclasses import dataclass
from shared.models import WeatherConditions, CalendarState


@dataclass
class AggregatorState:
    last_weather: WeatherConditions | None = None
    last_calendar: CalendarState | None = None

    def update_weather(self, w: WeatherConditions) -> None:
        self.last_weather = w

    def update_calendar(self, c: CalendarState) -> None:
        self.last_calendar = c

    def to_dict(self) -> dict:
        weather = None
        if self.last_weather:
            w = self.last_weather
            weather = {
                "provider": w.provider,
                "timestamp": w.timestamp.isoformat(),
                "temperature_c": w.temperature_c,
                "conditions": w.conditions,
                "humidity_pct": w.humidity_pct,
                "wind_speed_ms": w.wind_speed_ms,
                "icon_code": w.icon_code,
            }
        calendar = None
        if self.last_calendar:
            c = self.last_calendar
            calendar = {
                "poll_timestamp": c.poll_timestamp.isoformat(),
                "events": [
                    {"event_id": e.event_id, "summary": e.summary, "start": e.start, "end": e.end, "all_day": e.all_day}
                    for e in c.events
                ],
            }
        return {"weather": weather, "calendar": calendar}
