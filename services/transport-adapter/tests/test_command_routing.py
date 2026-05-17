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
    assert item["message_id"] == "test-uuid"


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
    assert item["message_id"] == "test-uuid-2"
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
