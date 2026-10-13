import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from transport_adapter import state
from transport_adapter.ws_handler import _read_loop, giga_websocket_handler


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
