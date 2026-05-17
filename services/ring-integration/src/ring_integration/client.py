from __future__ import annotations

from typing import Callable

from ring_doorbell import Auth, Ring, RingEventKind, RingEventListener

from shared.logging import make_logger, log_event

logger = make_logger("ring-integration")

_KIND_DING = RingEventKind.DING.value  # "ding"


async def init_ring_client(
    refresh_token: str,
    on_token_updated: Callable[[dict], None],
) -> Ring:
    """Create an authenticated Ring client and verify connectivity.

    The refresh_token value is never logged.
    """
    auth = Auth(
        "HousePanel/0.1",
        {"refresh_token": refresh_token},
        on_token_updated,
    )
    await auth.async_refresh_tokens()  # exchange refresh_token for access_token
    ring = Ring(auth)
    await ring.async_update_data()
    log_event(logger, "ring_connected", device_count=len(ring.video_devices()))
    return ring


async def subscribe_to_doorbell_events(ring: Ring, on_ding: Callable) -> RingEventListener:
    """Subscribe to doorbell ding events via FCM push listener.

    ``on_ding`` is called as ``on_ding(device, ring_event)`` for every ding.
    Returns the started ``RingEventListener`` so the caller can stop it on shutdown.
    """
    listener = RingEventListener(ring)

    def _on_ring_event(ring_event) -> None:
        if ring_event.kind != _KIND_DING:
            return
        device = ring.get_device_by_api_id(ring_event.doorbot_id)
        on_ding(device, ring_event)

    listener.add_notification_callback(_on_ring_event)
    await listener.start()

    device_count = len(ring.video_devices())
    log_event(logger, "ring_subscribed", device_count=device_count)
    return listener
