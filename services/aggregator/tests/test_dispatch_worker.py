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
    # Simulate reset_timeout elapsed so it half-opens
    cb._opened_at -= 31.0
    assert cb.allow_request() is True  # transitions to half_open
    cb.record_success()
    assert cb.state == "closed"
    assert cb.allow_request() is True


def test_circuit_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.0)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is True  # half_open after timeout=0
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
    assert _ttl_for_priority(0) == 60.0
    assert _ttl_for_priority(4) == 60.0


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
    assert item.not_before > time.monotonic() - 0.1  # scheduled in the future


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
