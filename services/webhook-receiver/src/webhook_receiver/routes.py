from __future__ import annotations
import json
import os
from fastapi import APIRouter, Request, Response
from pydantic import ValidationError
from .auth import validate_hmac_signature
from .schemas import CameraWebhookPayloadV1, SystemAlertWebhookPayloadV1
from .forwarder import forward_to_aggregator
from shared.logging import make_logger, log_event

router = APIRouter()
logger = make_logger("webhook-receiver")


def _hmac_secret(env_var: str) -> str:
    val = os.environ.get(env_var, "")
    if not val:
        raise RuntimeError(f"Missing required env var: {env_var}")
    return val


@router.post("/v1/webhooks/camera", status_code=202)
async def camera_webhook(request: Request) -> Response:
    raw_body = await request.body()
    sig = request.headers.get("X-HousePanel-Signature")
    secret = _hmac_secret("WEBHOOK_SECRET_UNIFI")

    if not validate_hmac_signature(raw_body, sig, secret):
        log_event(logger, "webhook_rejected", source="unifi-protect", reason="invalid_hmac")
        return Response(status_code=401)

    try:
        payload = CameraWebhookPayloadV1.model_validate(json.loads(raw_body))
    except (ValidationError, json.JSONDecodeError) as exc:
        log_event(logger, "webhook_rejected", source="unifi-protect", reason="schema_invalid", detail=str(exc))
        return Response(status_code=400)

    log_event(logger, "webhook_received", source="unifi-protect", camera_name=payload.camera_name)
    await forward_to_aggregator({
        "source": "webhook-receiver",
        "event_type": "ticker",
        "timestamp": payload.timestamp,
        "priority": 1,
        "ttl_seconds": 60,
        "payload": {
            "camera_name": payload.camera_name,
            "narrative": payload.narrative,
            "gate": payload.gate,
        },
    })
    return Response(status_code=202)


@router.post("/v1/webhooks/system-alert", status_code=202)
async def system_alert_webhook(request: Request) -> Response:
    raw_body = await request.body()
    sig = request.headers.get("X-HousePanel-Signature")
    secret = _hmac_secret("WEBHOOK_SECRET_ATH")

    if not validate_hmac_signature(raw_body, sig, secret):
        log_event(logger, "webhook_rejected", source="arduino-temp-hum-ubuntu", reason="invalid_hmac")
        return Response(status_code=401)

    try:
        payload = SystemAlertWebhookPayloadV1.model_validate(json.loads(raw_body))
    except (ValidationError, json.JSONDecodeError) as exc:
        log_event(logger, "webhook_rejected", source="arduino-temp-hum-ubuntu", reason="schema_invalid", detail=str(exc))
        return Response(status_code=400)

    log_event(logger, "webhook_received", source="arduino-temp-hum-ubuntu", host_id=payload.host_id, alert_type=payload.alert_type, severity=payload.severity)
    await forward_to_aggregator({
        "source": "webhook-receiver",
        "event_type": "ticker",
        "timestamp": payload.timestamp,
        "priority": 2,
        "ttl_seconds": 60,
        "payload": {
            "alert_type": payload.alert_type,
            "severity": payload.severity,
            "message": payload.message,
            "host_id": payload.host_id,
            "temperature_c": payload.temperature_c,
            "humidity_pct": payload.humidity_pct,
        },
    })
    return Response(status_code=202)
