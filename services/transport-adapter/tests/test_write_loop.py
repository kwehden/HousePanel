from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from transport_adapter import state
from transport_adapter.ws_write_loop import ws_write_loop


def _reset_state():
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


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_interrupt_sent_before_normal():
    """Interrupt-queue item is dispatched before normal-queue item."""
    interrupt_cmd = {"cmd": "DOORBELL", "message_id": "int-1"}
    normal_cmd = {"cmd": "TICKER-APPEND", "message_id": "norm-1"}

    state.interrupt_queue.put_nowait(interrupt_cmd)
    state.normal_queue.put_nowait(normal_cmd)

    ws = _make_ws()
    task = asyncio.create_task(ws_write_loop(ws))

    # Allow the loop to process at least 2 iterations
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    calls = ws.send_text.call_args_list
    assert len(calls) >= 2, f"Expected at least 2 sends, got {len(calls)}"
    first_sent = json.loads(calls[0].args[0])
    assert first_sent["cmd"] == "DOORBELL", (
        f"Expected DOORBELL first but got {first_sent['cmd']}"
    )


@pytest.mark.asyncio
async def test_normal_blocked_during_ota():
    """During OTA pause, normal queue is not drained; interrupt still goes through."""
    state.ota_paused = True

    interrupt_cmd = {"cmd": "DOORBELL", "message_id": "int-ota"}
    normal_cmd = {"cmd": "TICKER-APPEND", "message_id": "norm-ota"}

    state.normal_queue.put_nowait(normal_cmd)
    state.interrupt_queue.put_nowait(interrupt_cmd)

    ws = _make_ws()
    task = asyncio.create_task(ws_write_loop(ws))

    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    calls = ws.send_text.call_args_list
    sent_cmds = [json.loads(c.args[0])["cmd"] for c in calls]

    # Interrupt was sent
    assert "DOORBELL" in sent_cmds, f"DOORBELL not sent; sent: {sent_cmds}"
    # Normal was NOT sent
    assert "TICKER-APPEND" not in sent_cmds, (
        f"TICKER-APPEND should not be sent during OTA; sent: {sent_cmds}"
    )
    # Normal still in queue
    assert state.normal_queue.qsize() == 1

    # Cleanup
    state.ota_paused = False
