"""Broadcast and lifecycle isolation for two physical GIGA panels."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from transport_adapter import state
from transport_adapter.main import app, _hourly_time_sync
from transport_adapter.routes import CommandRequest, internal_health, metrics, post_command
from transport_adapter.ws_handler import giga_websocket_handler
from tests.test_ws_handler import SocketHarness, stop_handlers


@pytest.fixture(autouse=True)
def snapshots(monkeypatch):
    monkeypatch.setattr("transport_adapter.state_refresh.request_poller_refresh", lambda: None)

    async def refresh(*, triggered_by, panel=None):
        await panel.normal_queue.put({"cmd": "TIME", "epoch": 123})

    monkeypatch.setattr("transport_adapter.state_refresh._refresh_state", refresh)


async def attach(panel_id, socket=None):
    socket = socket or SocketHarness()
    socket.hello()
    task = asyncio.create_task(giga_websocket_handler(socket.websocket, panel_id))
    await asyncio.wait_for(socket.sent.wait(), 1)
    socket.sent.clear()
    return socket, task


def frames(socket):
    return [json.loads(m["text"]) for m in socket.messages if m["type"] == "websocket.send"]


async def update():
    return await post_command(CommandRequest(cmd="SYSMON-UPDATE", priority=0,
                                             payload={"temp_c": 21.5}, event_id="both"))


@pytest.mark.asyncio
async def test_both_panels_receive_identical_updates_and_individual_metrics():
    first, t1 = await attach("primary")
    second, t2 = await attach("panel-2")
    try:
        assert not t1.done()
        assert (await update()).status_code == 202
        await asyncio.wait_for(asyncio.gather(first.sent.wait(), second.sent.wait()), 1)
        assert frames(first) == frames(second)
        assert frames(first)[-1]["cmd"] == "SYSMON_TEMP"
        health = await internal_health()
        assert all(p["connected"] for p in health["panels"].values())
        body = (await metrics()).body.decode()
        assert 'housepanel_panel_session_connected{panel_id="primary"} 1' in body
        assert 'housepanel_panel_session_connected{panel_id="panel-2"} 1' in body
    finally:
        await stop_handlers(t1, t2)


@pytest.mark.asyncio
async def test_second_panel_reconnect_cannot_replace_or_clear_first_panel():
    first, t1 = await attach("primary")
    second, t2 = await attach("panel-2")
    replacement_task = None
    try:
        primary_task = state.primary.active_websocket_task
        state.primary.ota_paused = True
        state.primary.normal_queue.put_nowait({"cmd": "TIME", "epoch": 999})
        replacement, replacement_task = await attach("panel-2")
        await asyncio.wait_for(t2, 1)
        assert state.primary.active_websocket_task is primary_task
        assert not primary_task.done()
        assert state.primary.ota_paused
        assert state.primary.normal_depth == 1
        assert not first.close_started.is_set()
        assert frames(replacement) == [{"cmd": "TIME", "epoch": 123}]
        replacement.disconnect()
        await asyncio.wait_for(replacement_task, 1)
        assert state.primary.giga_connected
        assert not state.panels["panel-2"].giga_connected
    finally:
        await stop_handlers(*[t for t in (t1, t2, replacement_task) if t is not None])


@pytest.mark.asyncio
async def test_ota_pause_and_post_ota_replay_are_local_to_second_panel():
    first, t1 = await attach("primary")
    second, t2 = await attach("panel-2")
    try:
        second.incoming.put_nowait({"type": "websocket.receive", "text": '{"cmd":"OTA-START"}'})
        await asyncio.wait_for(second.sent.wait(), 1)
        second.sent.clear()
        assert state.panels["panel-2"].ota_paused
        assert not state.primary.ota_paused
        assert (await update()).status_code == 202
        await asyncio.wait_for(first.sent.wait(), 1)
        await asyncio.sleep(0.1)
        assert frames(first)[-1]["cmd"] == "SYSMON_TEMP"
        assert all(f["cmd"] != "SYSMON_TEMP" for f in frames(second))
        first.sent.clear()
        second.incoming.put_nowait({"type": "websocket.receive", "text": '{"cmd":"OTA-END"}'})
        await asyncio.wait_for(second.sent.wait(), 1)
        assert frames(second)[-1] == {"cmd": "TIME", "epoch": 123}
        assert not first.sent.is_set()
    finally:
        await stop_handlers(t1, t2)


@pytest.mark.asyncio
async def test_full_second_queue_does_not_block_first_and_joins_slow_session():
    first, t1 = await attach("primary")
    second, t2 = await attach("panel-2")
    panel = state.panels["panel-2"]
    try:
        # Block the writer on a full socket while its bounded queue fills.
        blocked, release = asyncio.Event(), asyncio.Event()
        original_send = second.websocket.send_text

        async def slow_send(data):
            blocked.set()
            await release.wait()
            await original_send(data)

        second.websocket.send_text = slow_send
        panel.normal_queue.put_nowait({"cmd": "TIME", "epoch": 1})
        await asyncio.wait_for(blocked.wait(), 1)
        for _ in range(panel.normal_queue.maxsize):
            panel.normal_queue.put_nowait({"cmd": "TIME", "epoch": 2})
        assert (await update()).status_code == 202
        await asyncio.wait_for(first.sent.wait(), 1)
        await asyncio.wait_for(t2, 1)
        assert frames(first)[-1]["cmd"] == "SYSMON_TEMP"
        assert not t1.done()
        assert panel.dropped_batches_total == 1
        assert not panel.giga_connected
        assert {"type": "websocket.close", "code": 1013, "reason": ""} in second.messages
    finally:
        await stop_handlers(t1, t2)


@pytest.mark.asyncio
async def test_paused_full_panel_waits_for_ota_end_instead_of_disconnecting():
    state.primary.giga_connected = True
    second = state.panels["panel-2"]
    second.giga_connected = second.ota_paused = True
    for _ in range(second.normal_queue.maxsize):
        second.normal_queue.put_nowait({"cmd": "TIME", "epoch": 2})
    assert (await update()).status_code == 202
    assert not second.overloaded.is_set()
    assert second.dropped_batches_total == 1
    assert state.primary.normal_queue.qsize() == 1


@pytest.mark.asyncio
async def test_unknown_identity_is_rejected_without_allocating_a_panel():
    socket = SocketHarness()
    await giga_websocket_handler(socket.websocket, "unregistered")
    assert set(state.panels) == {"primary", "panel-2"}
    assert socket.messages == [{"type": "websocket.close", "code": 1008, "reason": ""}]


@pytest.mark.asyncio
async def test_two_panels_repeated_reconnects_leave_no_owned_tasks():
    baseline = asyncio.all_tasks()
    tasks = []
    try:
        for _ in range(20):
            _, first = await attach("primary")
            _, second = await attach("panel-2")
            tasks.extend((first, second))
        await stop_handlers(*tasks)
        assert asyncio.all_tasks() <= baseline
        assert all(not p.giga_connected and p.active_websocket_task is None for p in state.panels.values())
    finally:
        await stop_handlers(*tasks)


@pytest.mark.asyncio
async def test_hourly_time_sync_broadcasts_to_both_panels(monkeypatch):
    calls = 0
    async def tick(seconds):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError
    monkeypatch.setattr("transport_adapter.main.asyncio.sleep", tick)
    for panel in state.panels.values():
        panel.giga_connected = True
    with pytest.raises(asyncio.CancelledError):
        await _hourly_time_sync()
    frames = [p.normal_queue.get_nowait() for p in state.panels.values()]
    assert all(f["cmd"] == "TIME" for f in frames)


def test_legacy_and_named_websocket_routes_both_deliver_the_http_broadcast():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/panel") as first:
            first.send_json({"cmd": "HELLO"})
            assert first.receive_json()["cmd"] == "TIME"
            with client.websocket_connect("/ws/panels/panel-2") as second:
                second.send_json({"cmd": "HELLO", "hostname": "housepanel-2", "panel_id": "panel-2"})
                assert second.receive_json()["cmd"] == "TIME"
                response = client.post("/internal/commands", json={
                    "cmd": "SYSMON-UPDATE", "priority": 0, "payload": {"temp_c": 21.5}, "event_id": "two",
                })
                assert response.status_code == 202
                assert first.receive_json() == second.receive_json()
                health = client.get("/internal/health").json()["panels"]
                assert len([p for p in health.values() if p["connected"]]) == 2
                assert health["panel-2"]["hostname"] == "housepanel-2"
