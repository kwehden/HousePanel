"""Only doorbell presses may reach the panel.

Added after mutation testing: `if ring_event.kind != _KIND_DING: return` could
be flipped to `==` with the suite still green — inverting the filter so motion
events fire the doorbell overlay and actual presses are dropped.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ring_integration.client import subscribe_to_doorbell_events


def _listener_capture():
    """Capture the callback registered with RingEventListener."""
    listener = MagicMock()
    listener.start = AsyncMock()
    captured = {}
    listener.add_notification_callback = MagicMock(
        side_effect=lambda cb: captured.setdefault("cb", cb)
    )
    return listener, captured


def _ring() -> MagicMock:
    ring = MagicMock()
    ring.video_devices = MagicMock(return_value=["cam1"])
    ring.get_device_by_api_id = MagicMock(return_value="device-obj")
    return ring


async def _subscribe(on_ding):
    listener, captured = _listener_capture()
    with patch("ring_integration.client.RingEventListener", return_value=listener):
        await subscribe_to_doorbell_events(_ring(), on_ding)
    return captured["cb"]


@pytest.mark.asyncio
async def test_ding_event_is_forwarded():
    seen = []
    cb = await _subscribe(lambda device, ev: seen.append(ev))

    cb(MagicMock(kind="ding", doorbot_id=42))

    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["motion", "on_demand", "intercom_unlock", ""])
async def test_non_ding_events_are_dropped(kind):
    """A motion event must never render as a doorbell press."""
    seen = []
    cb = await _subscribe(lambda device, ev: seen.append(ev))

    cb(MagicMock(kind=kind, doorbot_id=42))

    assert seen == []


@pytest.mark.asyncio
async def test_device_is_resolved_from_the_event_doorbot_id():
    seen = []
    cb = await _subscribe(lambda device, ev: seen.append(device))

    cb(MagicMock(kind="ding", doorbot_id=99))

    assert seen == ["device-obj"]


@pytest.mark.asyncio
async def test_listener_is_started():
    listener, captured = _listener_capture()
    with patch("ring_integration.client.RingEventListener", return_value=listener):
        returned = await subscribe_to_doorbell_events(_ring(), lambda d, e: None)

    listener.start.assert_awaited_once()
    assert returned is listener
