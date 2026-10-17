import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect

from transport_adapter import state
from transport_adapter.ws_handler import _read_loop, giga_websocket_handler


@pytest.fixture(autouse=True)
def isolated_connection_state(monkeypatch):
    monkeypatch.setattr(state, "normal_queue", ObservedQueue())
    monkeypatch.setattr(state, "interrupt_queue", asyncio.Queue(maxsize=50))
    monkeypatch.setattr(state, "active_websocket", None)
    monkeypatch.setattr(state, "active_websocket_task", None)
    monkeypatch.setattr(state, "websocket_handover_lock", asyncio.Lock())
    monkeypatch.setattr(state, "giga_connected", False)
    monkeypatch.setattr(state, "ota_paused", False)


class ObservedQueue(asyncio.Queue):
    def __init__(self):
        super().__init__(maxsize=50)
        self.waiting = asyncio.Event()
        self.second_waiting = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.get_count = 0

    async def get(self):
        self.get_count += 1
        if self.get_count >= 2:
            self.second_waiting.set()
        self.waiting.set()
        try:
            return await super().get()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class SocketHarness:
    """Real Starlette socket with independently controlled ASGI receive/close."""

    def __init__(self, *, hold_close=False):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.messages = []
        self.accepted = asyncio.Event()
        self.sent = asyncio.Event()
        self.read_cancelled = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        if not hold_close:
            self.close_release.set()
        self.websocket = WebSocket(
            {"type": "websocket", "path": "/giga"}, self.receive, self.send
        )

    async def receive(self):
        try:
            return await self.incoming.get()
        except asyncio.CancelledError:
            self.read_cancelled.set()
            raise

    async def send(self, message):
        self.messages.append(message)
        if message["type"] == "websocket.accept":
            self.accepted.set()
        elif message["type"] == "websocket.send":
            self.sent.set()
        elif message["type"] == "websocket.close":
            self.close_started.set()
            await self.close_release.wait()

    def hello(self):
        self.incoming.put_nowait({"type": "websocket.receive", "text": '{"cmd":"HELLO"}'})

    def disconnect(self):
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})


async def stop_handlers(*tasks):
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["disconnect", "handover"])
async def test_replacement_discards_ota_backlog_before_delayed_hello(monkeypatch, termination):
    old, replacement = SocketHarness(), SocketHarness()
    fresh = {"cmd": "TIME", "epoch": 456}

    async def refresh(*, triggered_by):
        await state.normal_queue.put(fresh)

    monkeypatch.setattr("transport_adapter.state_refresh._refresh_state", refresh)
    monkeypatch.setattr("transport_adapter.state_refresh.request_poller_refresh", lambda: None)
    tasks = [asyncio.create_task(giga_websocket_handler(old.websocket))]
    try:
        await asyncio.wait_for(old.accepted.wait(), 1)
        old.incoming.put_nowait({"type": "websocket.receive", "text": '{"cmd":"OTA-START"}'})
        await asyncio.wait_for(old.sent.wait(), 1)
        # Let the writer observe OTA pause before building its backlog.
        await asyncio.sleep(0.1)
        state.normal_queue.put_nowait({"cmd": "TIME", "epoch": 123})
        if termination == "disconnect":
            old.disconnect()
            await asyncio.wait_for(tasks[0], 1)

        state.normal_queue.waiting.clear()
        tasks.append(asyncio.create_task(giga_websocket_handler(replacement.websocket)))
        await asyncio.wait_for(state.normal_queue.waiting.wait(), 1)
        assert state.active_websocket is replacement.websocket
        assert state.normal_queue.empty()
        assert not replacement.sent.is_set()

        replacement.hello()
        await asyncio.wait_for(replacement.sent.wait(), 1)
        assert [json.loads(item["text"]) for item in replacement.messages
                if item["type"] == "websocket.send"] == [fresh]
        replacement.disconnect()
        await asyncio.wait_for(tasks[1], 1)
    finally:
        await stop_handlers(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["disconnect", "cancel", "handover"])
async def test_interrupted_ota_does_not_pause_replacement(monkeypatch, termination):
    old, replacement = SocketHarness(), SocketHarness()
    frame = {"cmd": "TIME", "epoch": 123}

    async def refresh(_frame):
        await state.normal_queue.put(frame)

    monkeypatch.setattr("transport_adapter.ws_handler.handle_hello_frame", refresh)
    tasks = [asyncio.create_task(giga_websocket_handler(old.websocket))]
    try:
        await asyncio.wait_for(old.accepted.wait(), 1)
        old.incoming.put_nowait({"type": "websocket.receive", "text": '{"cmd":"OTA-START"}'})
        await asyncio.wait_for(old.sent.wait(), 1)
        assert state.ota_paused
        if termination == "disconnect":
            old.disconnect()
            await asyncio.wait_for(tasks[0], 1)
            assert not state.ota_paused
        elif termination == "cancel":
            tasks[0].cancel()
            await asyncio.gather(tasks[0], return_exceptions=True)
            assert not state.ota_paused

        replacement.hello()
        tasks.append(asyncio.create_task(giga_websocket_handler(replacement.websocket)))
        await asyncio.wait_for(replacement.sent.wait(), 1)
        await asyncio.gather(tasks[0], return_exceptions=True)
        assert not state.ota_paused
        assert state.giga_connected
        assert [json.loads(item["text"]) for item in replacement.messages
                if item["type"] == "websocket.send"] == [frame]
        assert state.normal_queue.empty()
        replacement.disconnect()
        await asyncio.wait_for(tasks[1], 1)
    finally:
        await stop_handlers(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_name", ["normal_queue", "interrupt_queue"])
async def test_handover_stops_old_reader_and_writer_before_hello(monkeypatch, queue_name):
    old, replacement = SocketHarness(), SocketHarness()
    frame = {"cmd": "TIME", "epoch": 123}
    old_queue = state.normal_queue
    hello_observations = []
    hello_seen = asyncio.Event()

    async def refresh(_frame):
        hello_observations.append((old.read_cancelled.is_set(), old_queue.cancelled.is_set()))
        await getattr(state, queue_name).put(frame)
        # Refresh performs HTTP I/O after enqueueing TIME in production.
        await asyncio.sleep(0)
        hello_seen.set()

    monkeypatch.setattr("transport_adapter.ws_handler.handle_hello_frame", refresh)
    old_task = asyncio.create_task(giga_websocket_handler(old.websocket))
    new_task = None
    try:
        await asyncio.wait_for(old_queue.waiting.wait(), 1)
        new_task = asyncio.create_task(giga_websocket_handler(replacement.websocket))
        await asyncio.wait_for(old_queue.second_waiting.wait(), 1)
        replacement.hello()
        await asyncio.wait_for(hello_seen.wait(), 1)
        assert hello_observations == [(True, True)]
        await asyncio.wait_for(replacement.sent.wait(), 1)
        await asyncio.wait_for(old_task, 1)
        assert not any(item["type"] == "websocket.send" for item in old.messages)
        assert [json.loads(item["text"]) for item in replacement.messages
                if item["type"] == "websocket.send"] == [frame]
        assert {"type": "websocket.close", "code": 1012, "reason": ""} in old.messages
        assert state.active_websocket is replacement.websocket
        replacement.disconnect()
        await asyncio.wait_for(new_task, 1)
        assert state.active_websocket_task is None
        assert state.active_websocket is None
        assert not state.giga_connected
    finally:
        await stop_handlers(*[task for task in (old_task, new_task) if task is not None])


@pytest.mark.asyncio
async def test_three_connections_serialize_handover_and_keep_latest_owner():
    old, middle, latest = SocketHarness(hold_close=True), SocketHarness(), SocketHarness()
    tasks = [asyncio.create_task(giga_websocket_handler(old.websocket))]
    try:
        await asyncio.wait_for(state.normal_queue.waiting.wait(), 1)
        tasks.append(asyncio.create_task(giga_websocket_handler(middle.websocket)))
        await asyncio.wait_for(old.close_started.wait(), 1)
        tasks.append(asyncio.create_task(giga_websocket_handler(latest.websocket)))
        await asyncio.wait_for(latest.accepted.wait(), 1)
        assert state.active_websocket is None
        assert state.active_websocket_task is None
        old.close_release.set()
        await asyncio.wait_for(middle.close_started.wait(), 1)
        await asyncio.wait_for(asyncio.gather(*tasks[:2]), 1)
        assert state.active_websocket is latest.websocket
        assert state.giga_connected
        await state.normal_queue.put({"cmd": "TIME", "epoch": 456})
        await asyncio.wait_for(latest.sent.wait(), 1)
        assert not any(item["type"] == "websocket.send" for item in middle.messages)
        latest.disconnect()
        await asyncio.wait_for(tasks[-1], 1)
        assert state.active_websocket_task is None
        assert state.active_websocket is None
        assert not state.giga_connected
    finally:
        old.close_release.set()
        await stop_handlers(*tasks)


@pytest.mark.asyncio
async def test_handover_cancels_in_progress_refresh_before_replacement_refresh(monkeypatch):
    old, replacement = SocketHarness(), SocketHarness()
    refresh_started = asyncio.Event()
    refresh_stopped = asyncio.Event()
    calls = 0

    async def refresh(_frame):
        nonlocal calls
        calls += 1
        if calls == 1:
            refresh_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                refresh_stopped.set()
        else:
            assert refresh_stopped.is_set()
            await state.normal_queue.put({"cmd": "TIME", "epoch": 789})

    monkeypatch.setattr("transport_adapter.ws_handler.handle_hello_frame", refresh)
    old.hello()
    tasks = [asyncio.create_task(giga_websocket_handler(old.websocket))]
    try:
        await asyncio.wait_for(refresh_started.wait(), 1)
        replacement.hello()
        tasks.append(asyncio.create_task(giga_websocket_handler(replacement.websocket)))
        await asyncio.wait_for(replacement.sent.wait(), 1)
        await asyncio.wait_for(tasks[0], 1)
        assert calls == 2
        assert refresh_stopped.is_set()
        replacement.disconnect()
        await asyncio.wait_for(tasks[1], 1)
        assert state.active_websocket_task is None
    finally:
        await stop_handlers(*tasks)


@pytest.mark.asyncio
async def test_handler_cancellation_joins_session_and_queue_waiter():
    socket = SocketHarness()
    task = asyncio.create_task(giga_websocket_handler(socket.websocket))
    try:
        await asyncio.wait_for(state.normal_queue.waiting.wait(), 1)
        session = state.active_websocket_task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert session is not None and session.done()
        assert socket.read_cancelled.is_set()
        assert state.normal_queue.cancelled.is_set()
        assert state.active_websocket_task is None
        assert state.active_websocket is None
        assert not state.giga_connected
    finally:
        await stop_handlers(task)


@pytest.mark.asyncio
async def test_repeated_reconnects_leave_no_connection_tasks():
    baseline = asyncio.all_tasks()
    tasks = []
    previous_session = None
    try:
        for _ in range(25):
            state.normal_queue.waiting.clear()
            socket = SocketHarness()
            tasks.append(asyncio.create_task(giga_websocket_handler(socket.websocket)))
            await asyncio.wait_for(state.normal_queue.waiting.wait(), 1)
            if len(tasks) > 1:
                await asyncio.wait_for(tasks[-2], 1)
                assert previous_session is not None and previous_session.done()
            assert state.active_websocket is socket.websocket
            previous_session = state.active_websocket_task
        socket.disconnect()
        await asyncio.wait_for(tasks[-1], 1)
        assert previous_session is not None and previous_session.done()
        assert state.active_websocket_task is None
        assert state.active_websocket is None
        assert not state.giga_connected
        assert asyncio.all_tasks() <= baseline
    finally:
        await stop_handlers(*tasks)


@pytest.mark.asyncio
async def test_malformed_and_non_object_frames_do_not_crash_parser():
    websocket = MagicMock()
    websocket.receive_text = AsyncMock(side_effect=["[]", "null", "{bad", WebSocketDisconnect()])
    with pytest.raises(WebSocketDisconnect):
        await _read_loop(websocket)
    assert websocket.receive_text.await_count == 4


@pytest.mark.asyncio
async def test_new_connection_closes_superseded_socket_and_cleans_owned_tasks():
    state.normal_queue = asyncio.Queue(maxsize=50)
    state.interrupt_queue = asyncio.Queue(maxsize=50)
    state.ota_paused = False
    previous = MagicMock()
    previous.close = AsyncMock()
    state.active_websocket = previous
    release = asyncio.Event()

    async def receive():
        await release.wait()
        raise WebSocketDisconnect()

    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.receive_text = AsyncMock(side_effect=receive)
    task = asyncio.create_task(giga_websocket_handler(websocket))
    try:
        await asyncio.sleep(0)
        previous.close.assert_awaited_once_with(code=1012)
        assert state.active_websocket is websocket
        release.set()
        await task
        assert state.active_websocket is None
        assert not state.giga_connected
    finally:
        release.set()
        await task
