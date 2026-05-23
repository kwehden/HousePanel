from __future__ import annotations
import asyncio
import enum
import itertools
import os
import random
import time
from dataclasses import dataclass, field

import httpx

from shared.logging import make_logger, log_event

logger = make_logger("aggregator")

_BACKOFF_BASE = 0.5
_BACKOFF_MAX = 30.0
_FAILURE_THRESHOLD = 5
_RESET_TIMEOUT = 30.0


def _ttl_for_priority(priority: int) -> float:
    if priority >= 90:
        return 300.0   # urgent (doorbell): 5 min
    if priority >= 5:
        return 120.0   # structured updates (weather, calendar, sysmon ≥5): 2 min
    return 90.0        # sysmon priority-0: matches 90s display staleness threshold


@dataclass(order=True)
class _Command:
    """Priority-queue item.  Compare by (neg_priority, seq) only."""
    neg_priority: int
    seq: int
    not_before: float = field(compare=False)
    expires_at: float = field(compare=False)
    attempts: int = field(compare=False)
    cmd: str = field(compare=False)
    body: dict = field(compare=False)
    event_id: str = field(compare=False)


class _CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = _FAILURE_THRESHOLD,
        reset_timeout: float = _RESET_TIMEOUT,
    ) -> None:
        self._state = _CircuitState.CLOSED
        self._failures = 0
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        return self._state.value

    def allow_request(self) -> bool:
        if self._state == _CircuitState.CLOSED:
            return True
        if self._state == _CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self._reset_timeout:
                # Grant exactly one probe slot; state stays HALF_OPEN until the
                # probe outcome arrives via record_success or record_failure.
                self._state = _CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN: probe already dispatched — block until outcome is recorded.
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = _CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == _CircuitState.HALF_OPEN or self._failures >= self._failure_threshold:
            self._state = _CircuitState.OPEN
            self._opened_at = time.monotonic()


class DispatchWorker:
    """Async priority queue + circuit breaker for aggregator→transport-adapter delivery."""

    def __init__(self, transport_url: str, maxsize: int = 200) -> None:
        self._url = f"{transport_url}/internal/commands"
        self._queue: asyncio.PriorityQueue[_Command] = asyncio.PriorityQueue(maxsize=maxsize)
        self._circuit = CircuitBreaker()
        self._seq: itertools.count = itertools.count()

    # -- public API ----------------------------------------------------------

    def enqueue(self, cmd: str, priority: int, payload: dict, event_id: str) -> None:
        now = time.monotonic()
        item = _Command(
            neg_priority=-priority,
            seq=next(self._seq),
            not_before=now,
            expires_at=now + _ttl_for_priority(priority),
            attempts=0,
            cmd=cmd,
            body={"cmd": cmd, "priority": priority, "payload": payload, "event_id": event_id},
            event_id=event_id,
        )
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            log_event(logger, "dispatch_queue_full", level="warning", cmd=cmd, event_id=event_id)

    async def run(self) -> None:
        while True:
            # If circuit is open, pause before trying to drain
            if not self._circuit.allow_request():
                log_event(
                    logger,
                    "circuit_open",
                    level="warning",
                    state=self._circuit.state,
                    queue_depth=self._queue.qsize(),
                )
                await asyncio.sleep(1.0)
                continue

            # Non-blocking peek — sleep briefly when idle
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
                continue

            now = time.monotonic()

            # Drop commands whose TTL has elapsed
            if now > item.expires_at:
                log_event(
                    logger, "command_expired",
                    cmd=item.cmd, event_id=item.event_id, attempts=item.attempts,
                )
                continue

            # Command not yet eligible for retry — put it back and yield briefly
            if now < item.not_before:
                try:
                    self._queue.put_nowait(item)
                except asyncio.QueueFull:
                    log_event(
                        logger, "dispatch_queue_full_on_reinsert",
                        level="warning", cmd=item.cmd, event_id=item.event_id,
                    )
                await asyncio.sleep(min(0.1, item.not_before - now))
                continue

            await self._attempt(item)

    # -- internals -----------------------------------------------------------

    async def _attempt(self, item: _Command) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._url, json=item.body)

            if resp.status_code in (200, 202, 204):
                self._circuit.record_success()
                log_event(logger, "command_dispatched", cmd=item.cmd, event_id=item.event_id)
                return

            if resp.status_code == 503:
                # Transport-adapter queue full — honour the back-pressure signal
                log_event(
                    logger, "command_backpressure",
                    level="warning", cmd=item.cmd, event_id=item.event_id,
                )
            else:
                log_event(
                    logger, "command_http_error",
                    level="warning", cmd=item.cmd, event_id=item.event_id,
                    status=resp.status_code,
                )

            self._circuit.record_failure()

        except (httpx.TransportError, httpx.TimeoutException) as exc:
            log_event(
                logger, "command_network_error",
                level="warning", cmd=item.cmd, event_id=item.event_id, error=str(exc),
            )
            self._circuit.record_failure()

        self._requeue_with_backoff(item)

    def _requeue_with_backoff(self, item: _Command) -> None:
        item.attempts += 1
        jitter = random.uniform(0, 0.5)
        delay = min(_BACKOFF_BASE * (2 ** item.attempts) + jitter, _BACKOFF_MAX)
        item.not_before = time.monotonic() + delay
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            log_event(
                logger, "dispatch_queue_full_on_retry",
                level="warning", cmd=item.cmd, event_id=item.event_id,
            )


def create_worker() -> DispatchWorker:
    transport_url = os.environ.get(
        "TRANSPORT_ADAPTER_URL", "http://housepanel-transport-adapter:8002"
    )
    return DispatchWorker(transport_url=transport_url)
