from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from shared.models import WeatherConditions, CalendarState


@dataclass
class SysmonData:
    temp_c: float
    history: list[float]
    label: str
    timestamp: datetime


@dataclass
class AggregatorState:
    last_weather: WeatherConditions | None = None
    last_calendar: CalendarState | None = None
    last_sysmon: SysmonData | None = None

    def update_weather(self, w: WeatherConditions) -> None:
        self.last_weather = w

    def update_calendar(self, c: CalendarState) -> None:
        self.last_calendar = c

    def update_sysmon(self, s: SysmonData) -> None:
        self.last_sysmon = s

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
                "today_high_c": w.today_high_c,
                "today_low_c": w.today_low_c,
                "forecast": [
                    {"day_label": d.day_label, "high_c": d.high_c, "low_c": d.low_c, "conditions": d.conditions}
                    for d in w.forecast
                ],
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
        sysmon = None
        if self.last_sysmon:
            s = self.last_sysmon
            sysmon = {
                "temp_c": s.temp_c,
                "history": s.history,
                "label": s.label,
                "timestamp": s.timestamp.isoformat(),
            }
        return {"weather": weather, "calendar": calendar, "sysmon": sysmon}
