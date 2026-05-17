"""Tests for ring_integration.normalizer."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from ring_integration.normalizer import normalize_ring_event


def _make_device(device_id: int = 12345, name: str = "Front Door") -> MagicMock:
    device = MagicMock()
    device.id = device_id
    device.name = name
    return device


def test_normalize_ring_event_fields_present() -> None:
    """All required top-level and payload fields must be present."""
    device = _make_device()
    result = normalize_ring_event(device)

    assert "source" in result
    assert "event_type" in result
    assert "timestamp" in result
    assert "priority" in result
    assert "payload" in result

    payload = result["payload"]
    assert "device_id" in payload
    assert "device_name" in payload
    assert "event_id" in payload


def test_normalize_ring_event_values() -> None:
    """source, event_type, and priority must match the contract."""
    device = _make_device(device_id=42, name="Back Door")
    result = normalize_ring_event(device)

    assert result["source"] == "ring"
    assert result["event_type"] == "doorbell-interrupt"
    assert result["priority"] == 99
    assert result["payload"]["device_id"] == "42"
    assert result["payload"]["device_name"] == "Back Door"


def test_normalize_ring_event_uuid4() -> None:
    """event_id must be a valid UUID4 string."""
    device = _make_device()
    result = normalize_ring_event(device)

    event_id = result["payload"]["event_id"]
    parsed = uuid.UUID(event_id)
    assert parsed.version == 4


def test_normalize_ring_event_unique_event_ids() -> None:
    """Each call produces a distinct event_id."""
    device = _make_device()
    id1 = normalize_ring_event(device)["payload"]["event_id"]
    id2 = normalize_ring_event(device)["payload"]["event_id"]
    assert id1 != id2


def test_normalize_ring_event_with_ding_event_arg() -> None:
    """Passing a ding_event argument must not raise and result is unchanged."""
    device = _make_device()
    ding_event = MagicMock()
    result = normalize_ring_event(device, ding_event)
    assert result["event_type"] == "doorbell-interrupt"


def test_normalize_ring_event_timestamp_is_string() -> None:
    """timestamp must be a non-empty ISO8601 string."""
    device = _make_device()
    result = normalize_ring_event(device)
    assert isinstance(result["timestamp"], str)
    assert len(result["timestamp"]) > 0
