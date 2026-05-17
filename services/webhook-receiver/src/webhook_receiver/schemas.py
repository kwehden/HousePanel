from __future__ import annotations
from pydantic import BaseModel, Field


class CameraWebhookPayloadV1(BaseModel):
    schema_version: str = Field(pattern=r"^1$")
    source: str = Field(pattern=r"^unifi-protect$")
    timestamp: str
    camera_name: str = Field(min_length=1)
    camera_id: str | None = None
    narrative: str = Field(min_length=1)
    gate: dict | None = None


class SystemAlertWebhookPayloadV1(BaseModel):
    schema_version: str = Field(pattern=r"^1$")
    source: str = Field(pattern=r"^arduino-temp-hum-ubuntu$")
    host_id: str = Field(min_length=1)
    timestamp: str
    alert_type: str = Field(pattern=r"^(temperature|humidity|system|network)$")
    severity: str = Field(pattern=r"^(info|warning|critical)$")
    message: str = Field(min_length=1, max_length=200)
    temperature_c: float | None = None
    humidity_pct: float | None = None
