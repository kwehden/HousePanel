from __future__ import annotations
import asyncio
import os
from collections import deque
from datetime import datetime, timezone
from shared.models import UnifiedEvent
from shared.logging import make_logger, log_event

logger = make_logger("aggregator")

TICKER_QUEUE_MAX_DEPTH = int(os.environ.get("TICKER_QUEUE_MAX_DEPTH", "20"))
TICKER_EVENT_TTL_SECONDS = int(os.environ.get("TICKER_EVENT_TTL_SECONDS", "60"))


class TickerQueue:
    def __init__(self) -> None:
        self._q: deque[UnifiedEvent] = deque(maxlen=TICKER_QUEUE_MAX_DEPTH)
        self._lock = asyncio.Lock()

    async def enqueue(self, event: UnifiedEvent) -> bool:
        async with self._lock:
            if len(self._q) == self._q.maxlen:
                log_event(logger, "ticker_dropped_overflow", event_id=event.event_id)
            self._q.append(event)
            return True

    async def dequeue_non_expired(self) -> UnifiedEvent | None:
        async with self._lock:
            now = datetime.now(timezone.utc)
            while self._q:
                event = self._q[0]
                age = (now - event.timestamp).total_seconds()
                if age > event.ttl_seconds:
                    self._q.popleft()
                    continue
                return self._q.popleft()
            return None

    async def snapshot(self) -> list[UnifiedEvent]:
        async with self._lock:
            now = datetime.now(timezone.utc)
            return [
                e for e in self._q
                if (now - e.timestamp).total_seconds() <= e.ttl_seconds
            ]
