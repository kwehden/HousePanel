import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

os.environ.setdefault("WEBHOOK_SECRET_UNIFI", "test-unifi-secret")
os.environ.setdefault("WEBHOOK_SECRET_ATH", "test-ath-secret")
os.environ.setdefault("AGGREGATOR_URL", "http://mock-aggregator:8001")

from webhook_receiver.main import app

client = TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


CAMERA_PAYLOAD = {
    "schema_version": "1",
    "source": "unifi-protect",
    "timestamp": "2026-05-17T12:00:00Z",
    "camera_name": "Front Door",
    "narrative": "A person approaches the door.",
}

ALERT_PAYLOAD = {
    "schema_version": "1",
    "source": "arduino-temp-hum-ubuntu",
    "host_id": "laminarflow",
    "timestamp": "2026-05-17T12:00:00Z",
    "alert_type": "temperature",
    "severity": "warning",
    "message": "Temperature above threshold: 32.5C",
    "temperature_c": 32.5,
}


@patch("webhook_receiver.routes.forward_to_aggregator", new_callable=AsyncMock)
def test_camera_webhook_valid(mock_fwd):
    body = json.dumps(CAMERA_PAYLOAD).encode()
    sig = _sign(body, "test-unifi-secret")
    resp = client.post("/v1/webhooks/camera", content=body, headers={"X-HousePanel-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 202
    mock_fwd.assert_awaited_once()


@patch("webhook_receiver.routes.forward_to_aggregator", new_callable=AsyncMock)
def test_system_alert_webhook_valid(mock_fwd):
    body = json.dumps(ALERT_PAYLOAD).encode()
    sig = _sign(body, "test-ath-secret")
    resp = client.post("/v1/webhooks/system-alert", content=body, headers={"X-HousePanel-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 202
    mock_fwd.assert_awaited_once()


def test_camera_webhook_invalid_hmac():
    body = json.dumps(CAMERA_PAYLOAD).encode()
    resp = client.post("/v1/webhooks/camera", content=body, headers={"X-HousePanel-Signature": "sha256=badhex", "Content-Type": "application/json"})
    assert resp.status_code == 401


def test_camera_webhook_malformed_json():
    body = b"not-json"
    sig = _sign(body, "test-unifi-secret")
    resp = client.post("/v1/webhooks/camera", content=body, headers={"X-HousePanel-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 400


def test_camera_webhook_wrong_schema_version():
    bad = {**CAMERA_PAYLOAD, "schema_version": "99"}
    body = json.dumps(bad).encode()
    sig = _sign(body, "test-unifi-secret")
    resp = client.post("/v1/webhooks/camera", content=body, headers={"X-HousePanel-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 400


def test_camera_webhook_missing_required_field():
    bad = {k: v for k, v in CAMERA_PAYLOAD.items() if k != "narrative"}
    body = json.dumps(bad).encode()
    sig = _sign(body, "test-unifi-secret")
    resp = client.post("/v1/webhooks/camera", content=body, headers={"X-HousePanel-Signature": sig, "Content-Type": "application/json"})
    assert resp.status_code == 400


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
