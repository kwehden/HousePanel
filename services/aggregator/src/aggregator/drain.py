from __future__ import annotations
import asyncio
import os
from shared.logging import make_logger, log_event
from .queue import TickerQueue
from .transport_client import dispatch_command_to_transport

logger = make_logger("aggregator")

TICKER_DRAIN_INTERVAL_SECONDS = float(os.environ.get("TICKER_DRAIN_INTERVAL_SECONDS", "1.0"))


async def ticker_drain_loop(queue: TickerQueue) -> None:
    while True:
        await asyncio.sleep(TICKER_DRAIN_INTERVAL_SECONDS)
        event = await queue.dequeue_non_expired()
        if event is not None:
            await dispatch_command_to_transport(
                cmd="TICKER-APPEND",
                priority=event.priority,
                payload=event.payload,
                event_id=event.event_id,
            )
