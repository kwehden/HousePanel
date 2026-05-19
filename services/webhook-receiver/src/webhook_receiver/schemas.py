from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class CameraWebhookV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(alias="schema", pattern=r"^camera-webhook-v1$")
    event_id: str
    camera_id: str
    camera_label: str = Field(min_length=1)
    ts: str
    ts_epoch: int
    suppressed: bool
    scene_summary: str = Field(min_length=1)
    gate_passed: bool
    snapshot_path: str


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
