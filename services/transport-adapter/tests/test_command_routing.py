from __future__ import annotations
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from transport_adapter import state
from transport_adapter.main import app


def _reset_state():
    """Replace module-level queues and reset flags between tests."""
    state.interrupt_queue = asyncio.Queue(maxsize=50)
    state.normal_queue = asyncio.Queue(maxsize=50)
    state.giga_connected = False
    state.ota_paused = False
    state.active_websocket = None


@pytest.fixture(autouse=True)
def reset_state_fixture():
    _reset_state()
    yield
    _reset_state()


@pytest.mark.asyncio
async def test_doorbell_goes_to_interrupt_queue():
    """priority=99 command lands in interrupt_queue; normal_queue stays empty."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/internal/commands", json={
            "cmd": "DOORBELL",
            "priority": 99,
            "payload": {},
            "event_id": "test-uuid",
        })
    assert resp.status_code == 202
    assert state.interrupt_queue.qsize() == 1
    assert state.normal_queue.qsize() == 0
    item = state.interrupt_queue.get_nowait()
    assert item["cmd"] == "DOORBELL"


@pytest.mark.asyncio
async def test_normal_command_goes_to_normal_queue():
    """Low-priority command lands in normal_queue; interrupt_queue stays empty."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/internal/commands", json={
            "cmd": "TICKER-APPEND",
            "priority": 10,
            "payload": {"text": "hello", "ttl_seconds": 30},
            "event_id": "test-uuid-2",
        })
    assert resp.status_code == 202
    assert state.normal_queue.qsize() == 1
    assert state.interrupt_queue.qsize() == 0
    item = state.normal_queue.get_nowait()
    assert item["cmd"] == "TICKER-APPEND"
    assert item["text"] == "hello"


@pytest.mark.asyncio
async def test_normal_queue_full_returns_503():
    """Posting to a full normal_queue returns 503."""
    # Fill queue to capacity
    for i in range(50):
        state.normal_queue.put_nowait({"cmd": "TICKER-APPEND", "seq": i})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/internal/commands", json={
            "cmd": "TICKER-APPEND",
            "priority": 10,
            "payload": {},
            "event_id": "overflow-uuid",
        })
    assert resp.status_code == 503
    assert resp.json() == {"error": "normal queue full"}


# ---------------------------------------------------------------------------
# Queue-full boundary — decides when back-pressure (503) is signalled
#
# Added after mutation testing: `qsize() + len(items) > maxsize` could become
# `>=` with the suite green, rejecting the command that exactly fills the queue.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_command_that_exactly_fills_the_queue_is_accepted():
    from transport_adapter.routes import CommandRequest, post_command
    while not state.normal_queue.empty():
        state.normal_queue.get_nowait()
    for _ in range(state.normal_queue.maxsize - 1):
        state.normal_queue.put_nowait({"cmd": "FILLER"})

    resp = await post_command(CommandRequest(
        cmd="SYSMON-UPDATE", priority=0, payload={"temp_c": 20.0}, event_id="fits"))

    assert resp.status_code == 202
    assert state.normal_queue.qsize() == state.normal_queue.maxsize


@pytest.mark.asyncio
async def test_command_that_would_overflow_is_refused_with_503():
    from transport_adapter.routes import CommandRequest, post_command
    while not state.normal_queue.empty():
        state.normal_queue.get_nowait()
    for _ in range(state.normal_queue.maxsize):
        state.normal_queue.put_nowait({"cmd": "FILLER"})

    resp = await post_command(CommandRequest(
        cmd="SYSMON-UPDATE", priority=0, payload={"temp_c": 20.0}, event_id="over"))

    assert resp.status_code == 503
    assert state.normal_queue.qsize() == state.normal_queue.maxsize


@pytest.mark.asyncio
async def test_doorbell_bypasses_the_full_normal_queue():
    """Priority 99 uses the interrupt queue, so a full normal queue must not
    swallow a doorbell press."""
    from transport_adapter.routes import CommandRequest, post_command
    while not state.normal_queue.empty():
        state.normal_queue.get_nowait()
    while not state.interrupt_queue.empty():
        state.interrupt_queue.get_nowait()
    for _ in range(state.normal_queue.maxsize):
        state.normal_queue.put_nowait({"cmd": "FILLER"})

    resp = await post_command(CommandRequest(
        cmd="DOORBELL", priority=99, payload={}, event_id="ding"))

    assert resp.status_code == 202
    assert state.interrupt_queue.qsize() >= 1
