import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

from transport_adapter import state
from transport_adapter.memory_telemetry import MemorySample
from transport_adapter.routes import internal_health, metrics
from transport_adapter.ws_handler import _read_loop, giga_websocket_handler
from transport_adapter.main import app
from tests.test_ws_handler import SocketHarness, stop_handlers


def sample(**changes):
    return dict(cmd="MEMORY", version=1, boot_id="0123456789abcdef", uptime_ms=60000,
                heap_current=1000, heap_peak=2000, heap_reserved=3000,
                alloc_count=20, alloc_failures=0, stack_high_water=800,
                stack_reserved=2000, stack_count=3, stack_min_free=200,
                stack_complete=True, gui_used=100, gui_peak=120,
                gui_total=1024, gui_largest_free=500) | changes


@pytest.fixture(autouse=True)
def no_refresh(monkeypatch):
    monkeypatch.setattr("transport_adapter.ws_handler.handle_hello_frame", AsyncMock())


async def read_samples(panel, *samples, hello=True):
    raw = ([json.dumps({"cmd": "HELLO"})] if hello else []) + [
        json.dumps(s) if not isinstance(s, str) else s for s in samples]
    socket = AsyncMock()
    socket.receive_text.side_effect = [*raw, WebSocketDisconnect()]
    with pytest.raises(WebSocketDisconnect):
        await _read_loop(socket, panel=panel)


@pytest.mark.parametrize("changes", [
    {"heap_current": -1}, {"heap_peak": 999}, {"alloc_count": 2**32},
    {"alloc_count": True}, {"alloc_count": "1"}, {"version": True},
    {"version": 2}, {"uptime_ms": -1}, {"uptime_ms": 2**63},
    {"boot_id": "x" * 17}, {"boot_id": "invalid"},
    {"stack_high_water": 2001}, {"stack_min_free": 2001}, {"stack_min_free": 1201},
    {"stack_count": 33}, {"stack_count": 0}, {"stack_complete": 1},
    {"gui_used": 1025}, {"gui_largest_free": 1000},
    {"panel_id": "panel-2"}, {"anything": "unbounded"},
])
def test_strict_bounded_schema(changes):
    with pytest.raises(ValidationError):
        MemorySample.model_validate(sample(**changes))


@pytest.mark.asyncio
async def test_both_panels_have_independent_metrics_and_no_dynamic_labels():
    for i, panel in enumerate(state.panels.values()):
        panel.giga_connected = True
        await read_samples(panel, sample(heap_current=1000 + i))
    health = await internal_health()
    assert health["panels"]["primary"]["memory"]["heap_current"] == 1000
    assert health["panels"]["panel-2"]["memory"]["heap_current"] == 1001
    body = (await metrics()).body.decode()
    assert 'housepanel_panel_memory_heap_allocated_bytes{panel_id="primary"} 1000' in body
    assert 'housepanel_panel_memory_heap_allocated_bytes{panel_id="panel-2"} 1001' in body
    assert "0123456789abcdef" not in body
    assert 'housepanel_panel_memory_uptime_seconds{panel_id="primary"} 60' in body
    assert "housepanel_panel_memory_last_sample_timestamp_seconds" in body


@pytest.mark.asyncio
async def test_legacy_and_disconnected_panels_have_no_fake_zero_memory():
    state.primary.giga_connected = True
    health = await internal_health()
    assert all(p["memory"] is None for p in health["panels"].values())
    assert "housepanel_panel_memory_" not in (await metrics()).body.decode()
    await read_samples(state.primary, sample())
    state.primary.giga_connected = False
    assert "housepanel_panel_memory_" not in (await metrics()).body.decode()


@pytest.mark.asyncio
async def test_invalid_oversized_missing_and_prehello_samples_do_not_replace_data():
    panel = state.primary
    await read_samples(panel, sample(), hello=False)
    assert panel.memory is None
    await read_samples(panel, "x" * 1025, sample(heap_current=-1), {"cmd": "MEMORY"}, "{bad")
    assert panel.memory is None
    await read_samples(panel, sample())
    original = panel.memory
    await read_samples(panel, sample(heap_current=1001), sample(heap_current=-1))
    assert panel.memory is original


@pytest.mark.asyncio
async def test_latest_only_rate_limit_reboot_and_uptime_order(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("transport_adapter.ws_handler.time.monotonic", lambda: clock[0])
    panel = state.primary
    await read_samples(panel, sample())
    first = panel.memory
    clock[0] = 1
    await read_samples(panel, sample(uptime_ms=120000))
    assert panel.memory is first
    clock[0] = 6
    await read_samples(panel, sample(uptime_ms=59999))
    assert panel.memory is first
    await read_samples(panel, sample(uptime_ms=120000))
    assert panel.memory.uptime_ms == 120000
    clock[0] = 12
    await read_samples(panel, sample(boot_id="fedcba9876543210", uptime_ms=1))
    assert panel.memory.uptime_ms == 1
    assert panel.memory.boot_id != first.boot_id
    for i in range(1000):
        clock[0] += 6
        await read_samples(panel, sample(boot_id="fedcba9876543210", uptime_ms=i + 2))
    assert panel.memory.uptime_ms == 1001
    assert len(state.panels) == 2


@pytest.mark.asyncio
async def test_partial_stack_sample_exports_heap_but_not_partial_stack_totals():
    state.primary.giga_connected = True
    await read_samples(state.primary, sample(stack_complete=False))
    body = (await metrics()).body.decode()
    assert 'housepanel_panel_memory_stack_complete{panel_id="primary"} 0' in body
    assert "housepanel_panel_memory_stack_high_water_bytes" not in body
    assert "housepanel_panel_memory_heap_allocated_bytes" in body


def test_real_legacy_and_named_sockets_receive_telemetry_without_echo_or_fanout():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/panel") as primary:
            with client.websocket_connect("/ws/panels/panel-2") as second:
                for ws in (primary, second):
                    ws.send_json({"cmd": "HELLO"})
                primary.send_json(sample(heap_current=1111))
                second.send_json(sample(heap_current=1222))
                # Round-trip each reader through its subsequent OTA handshake.
                for ws in (primary, second):
                    ws.send_json({"cmd": "OTA-START"})
                    assert ws.receive_json() == {"cmd": "OTA-PAUSE"}
                health = client.get("/internal/health").json()["panels"]
                assert health["primary"]["memory"]["heap_current"] == 1111
                assert health["panel-2"]["memory"]["heap_current"] == 1222
                assert all(p["normal_queue_depth"] == p["interrupt_queue_depth"] == 0 for p in health.values())
                body = client.get("/metrics").text
                assert 'housepanel_panel_memory_heap_allocated_bytes{panel_id="primary"} 1111' in body
                assert 'housepanel_panel_memory_heap_allocated_bytes{panel_id="panel-2"} 1222' in body


@pytest.mark.asyncio
async def test_disconnect_and_replacement_clear_only_owned_memory():
    primary, second = SocketHarness(), SocketHarness()
    primary.hello()
    second.hello()
    t1 = asyncio.create_task(giga_websocket_handler(primary.websocket))
    t2 = asyncio.create_task(giga_websocket_handler(second.websocket, "panel-2"))
    replacement_task = None
    try:
        await asyncio.wait_for(asyncio.gather(primary.reading.wait(), second.reading.wait()), 1)
        await read_samples(state.primary, sample())
        await read_samples(state.panels["panel-2"], sample())
        replacement = SocketHarness()
        replacement_task = asyncio.create_task(giga_websocket_handler(replacement.websocket, "panel-2"))
        await asyncio.wait_for(replacement.reading.wait(), 1)
        await asyncio.wait_for(t2, 1)
        assert state.panels["panel-2"].memory is None
        assert state.primary.memory is not None
        primary.disconnect()
        await asyncio.wait_for(t1, 1)
        assert state.primary.memory is None
    finally:
        await stop_handlers(*[t for t in (t1, t2, replacement_task) if t is not None])
