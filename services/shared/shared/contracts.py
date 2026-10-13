"""Validate wire payloads before retaining them in state or delivery queues."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]
MAX_PAYLOAD_BYTES = 256 * 1024


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ForecastPayload(Payload):
    day_label: str = Field(default="", max_length=16)
    high_c: float = 0
    low_c: float = 0
    conditions: str = Field(default="", max_length=512)


class WeatherPayload(Payload):
    provider: str = Field(default="unknown", max_length=64)
    timestamp: str | None = Field(default=None, max_length=64)
    temperature_c: float = 0
    conditions: str = Field(default="", max_length=512)
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    icon_code: str | None = Field(default=None, max_length=2048)
    today_high_c: float | None = None
    today_low_c: float | None = None
    forecast: list[ForecastPayload] = Field(default_factory=list, max_length=4)


class CalendarEventPayload(Payload):
    event_id: str = Field(default="", max_length=512)
    summary: str = Field(default="", max_length=1024)
    start: str = Field(default="", max_length=64)
    end: str = Field(default="", max_length=64)
    all_day: bool = Field(default=False, strict=True)


class CalendarPayload(Payload):
    poll_timestamp: str | None = Field(default=None, max_length=64)
    events: list[CalendarEventPayload] = Field(default_factory=list, max_length=500)


class SysmonPayload(Payload):
    temp_c: float = 0
    humidity_pct: float | None = None
    board_id: str = Field(default="", max_length=128)
    label: str = Field(default="Sensor", max_length=256)
    timestamp: str | None = Field(default=None, max_length=64)


def validate_payload(event_type: str, payload: JsonObject) -> JsonObject:
    encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("Payload exceeds 256 KiB")
    models: dict[str, type[Payload]] = {
        "weather-update": WeatherPayload, "calendar-update": CalendarPayload,
        "sysmon-update": SysmonPayload}
    model = models.get(event_type)
    if model is None:
        return payload
    return model.model_validate(payload).model_dump()
