from __future__ import annotations
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aggregator.dispatch_worker import CircuitBreaker, DispatchWorker, _ttl_for_priority


# ---------------------------------------------------------------------------
# CircuitBreaker unit tests
# ---------------------------------------------------------------------------

def test_circuit_starts_closed():
    cb = CircuitBreaker()
    assert cb.state == "closed"
    assert cb.allow_request() is True


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is False


def test_circuit_closes_on_success():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    # Simulate reset_timeout elapsed
    cb._opened_at -= 31.0
    # First allow_request() in OPEN after timeout: transitions to HALF_OPEN,
    # then allow_request() re-arms to OPEN and returns True (probe slot)
    assert cb.allow_request() is True
    cb.record_success()
    assert cb.state == "closed"
    assert cb.allow_request() is True


def test_circuit_half_open_gates_burst():
    """Only the first caller after reset_timeout gets the probe; subsequent callers see OPEN."""
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=60.0)
    cb.record_failure()
    assert cb.state == "open"
    # Simulate reset_timeout elapsed
    cb._opened_at -= 61.0
    # First call: gets the probe slot; circuit re-arms to OPEN with fresh opened_at
    assert cb.allow_request() is True
    # Second call: OPEN again but timeout has NOT elapsed — burst is gated
    assert cb.allow_request() is False


def test_circuit_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.0)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is True  # probe slot
    cb.record_failure()
    assert cb.state == "open"


def test_circuit_open_does_not_allow_until_timeout():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=60.0)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is False  # timeout not elapsed


# ---------------------------------------------------------------------------
# _ttl_for_priority
# ---------------------------------------------------------------------------

def test_ttl_high_priority():
    assert _ttl_for_priority(99) == 300.0
    assert _ttl_for_priority(90) == 300.0


def test_ttl_medium_priority():
    assert _ttl_for_priority(5) == 120.0
    assert _ttl_for_priority(10) == 120.0


def test_ttl_low_priority():
    assert _ttl_for_priority(0) == 90.0
    assert _ttl_for_priority(4) == 90.0


# ---------------------------------------------------------------------------
# DispatchWorker integration tests
# ---------------------------------------------------------------------------

def _make_worker(mock_post_response=None) -> tuple[DispatchWorker, AsyncMock]:
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    if mock_post_response is None:
        resp = MagicMock()
        resp.status_code = 202
    else:
        resp = mock_post_response
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return worker, mock_client


@pytest.mark.asyncio
async def test_successful_dispatch_clears_queue():
    worker, mock_client = _make_worker()
    worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="ev-1")
    assert worker._queue.qsize() == 1

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert worker._queue.qsize() == 0
    assert worker._circuit.state == "closed"


@pytest.mark.asyncio
async def test_503_triggers_backoff_requeue():
    """503 back-pressure causes item to be re-queued with a future not_before."""
    resp = MagicMock()
    resp.status_code = 503
    worker, mock_client = _make_worker(mock_post_response=resp)
    worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="ev-2")

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # After a 503, item is re-queued for later retry
    assert worker._queue.qsize() == 1
    item = worker._queue.get_nowait()
    assert item.attempts >= 1
    assert item.not_before > time.monotonic()  # scheduled in the future


@pytest.mark.asyncio
async def test_expired_command_is_dropped():
    worker, mock_client = _make_worker()
    worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id="ev-3")
    # Force immediate expiry
    item = worker._queue.get_nowait()
    item.expires_at = time.monotonic() - 1.0
    worker._queue.put_nowait(item)

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Expired item dropped without calling HTTP
    mock_client.post.assert_not_called()
    assert worker._queue.qsize() == 0


@pytest.mark.asyncio
async def test_priority_ordering():
    """High-priority command dispatched before low-priority even if enqueued later."""
    dispatched: list[str] = []

    async def fake_post(url, json=None, **kwargs):
        dispatched.append(json["cmd"])
        resp = MagicMock()
        resp.status_code = 202
        return resp

    worker = DispatchWorker(transport_url="http://test-transport:8002")
    # Enqueue low priority first
    worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id="low")
    worker.enqueue("DOORBELL", priority=99, payload={}, event_id="high")

    mock_client = AsyncMock()
    mock_client.post = fake_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(dispatched) >= 2
    assert dispatched.index("DOORBELL") < dispatched.index("SYSMON-UPDATE")


@pytest.mark.asyncio
async def test_queue_full_drops_gracefully():
    worker = DispatchWorker(transport_url="http://test-transport:8002", maxsize=2)
    worker.enqueue("A", priority=5, payload={}, event_id="1")
    worker.enqueue("B", priority=5, payload={}, event_id="2")
    # Third enqueue exceeds maxsize — should not raise
    worker.enqueue("C", priority=5, payload={}, event_id="3")
    assert worker._queue.qsize() == 2


@pytest.mark.asyncio
async def test_circuit_open_pauses_drain():
    """When circuit is open, no HTTP calls are made until reset_timeout elapses."""
    worker, mock_client = _make_worker()
    # Force circuit open with a long timeout
    worker._circuit._failure_threshold = 1
    worker._circuit._reset_timeout = 3600.0
    worker._circuit.record_failure()
    assert worker._circuit.state == "open"

    worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="ev-4")

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_client.post.assert_not_called()
    assert worker._queue.qsize() == 1  # item still waiting


# ---------------------------------------------------------------------------
# Regression: HALF_OPEN probe slot must not be consumed without a dispatch
#
# A GIGA hang fills the dispatch queue and opens the circuit.  If the outage
# outlasts the commands' TTL, the worker's next probe pops an expired command
# and drops it — consuming the probe slot without ever recording an outcome.
# HALF_OPEN had no other exit, so the breaker stayed wedged and the panel got
# no updates until the pod was restarted.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_command_does_not_wedge_circuit():
    """The probe that drops an expired command must not strand the breaker."""
    worker, mock_client = _make_worker()
    worker._circuit._failure_threshold = 1
    worker._circuit._reset_timeout = 30.0
    worker._circuit.record_failure()
    worker._circuit._opened_at -= 31.0  # probe is due

    # Queue holds only stale commands, as after a multi-hour outage.
    worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id="stale")
    stale = worker._queue.get_nowait()
    stale.expires_at = time.monotonic() - 1.0
    worker._queue.put_nowait(stale)

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.15)
        # The GIGA is healthy again — a fresh update must get through.
        worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="fresh")
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert mock_client.post.await_count == 1
    assert worker._circuit.state == "closed"
    assert worker._queue.qsize() == 0


def test_half_open_reclaims_an_unused_probe_slot():
    """A probe granted but never resolved is re-granted after reset_timeout."""
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=30.0)
    cb.record_failure()
    cb._opened_at -= 31.0
    assert cb.allow_request() is True
    assert cb.state == "half_open"
    assert cb.allow_request() is False  # probe outstanding

    cb._probe_granted_at -= 31.0  # outcome never arrived
    assert cb.allow_request() is True


@pytest.mark.asyncio
async def test_unexpected_error_records_failure_and_keeps_worker_alive():
    """A non-httpx error must resolve the probe rather than escape the loop."""
    worker, mock_client = _make_worker()
    mock_client.post = AsyncMock(side_effect=ValueError("unserialisable payload"))
    worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="boom")

    with patch("aggregator.dispatch_worker.httpx.AsyncClient", return_value=mock_client):
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.15)
        still_running = not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert still_running
    assert worker._circuit._failures >= 1


# ---------------------------------------------------------------------------
# Queue-full policy: reclaim stale commands rather than reject fresh ones
# ---------------------------------------------------------------------------

def test_full_queue_purges_expired_to_admit_fresh_command():
    worker = DispatchWorker(transport_url="http://test-transport:8002", maxsize=5)
    for i in range(5):
        worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id=f"stale-{i}")
    for item in list(worker._queue._queue):
        item.expires_at = time.monotonic() - 1.0
    assert worker._queue.qsize() == 5

    worker.enqueue("DOORBELL", priority=99, payload={}, event_id="fresh")

    assert worker._queue.qsize() == 1
    assert worker._queue.get_nowait().event_id == "fresh"


def test_full_queue_of_live_commands_still_rejects():
    """Live commands are never evicted — only past-TTL ones are reclaimed."""
    worker = DispatchWorker(transport_url="http://test-transport:8002", maxsize=3)
    for i in range(3):
        worker.enqueue("DOORBELL", priority=99, payload={}, event_id=f"live-{i}")

    worker.enqueue("WEATHER-UPDATE", priority=5, payload={}, event_id="rejected")

    assert worker._queue.qsize() == 3
    ids = {worker._queue.get_nowait().event_id for _ in range(3)}
    assert ids == {"live-0", "live-1", "live-2"}
