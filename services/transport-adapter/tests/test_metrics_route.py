from __future__ import annotations
import pytest
from transport_adapter import state
from transport_adapter.routes import metrics


async def _metrics_text() -> str:
    resp = await metrics()
    return resp.body.decode()


@pytest.fixture(autouse=True)
def _reset_state():
    state.primary.giga_connected = False
    state.frames_sent_total = 0
    state.last_frame_wall = None
    while not state.primary.interrupt_queue.empty():
        state.primary.interrupt_queue.get_nowait()
    while not state.primary.normal_queue.empty():
        state.primary.normal_queue.get_nowait()
    yield


@pytest.mark.asyncio
async def test_panel_connected_gauge_tracks_state():
    assert "housepanel_panel_connected 0" in await _metrics_text()
    state.primary.giga_connected = True
    assert "housepanel_panel_connected 1" in await _metrics_text()


@pytest.mark.asyncio
async def test_queue_depths_are_labelled_per_queue():
    state.primary.interrupt_queue.put_nowait({"cmd": "DOORBELL"})
    state.primary.normal_queue.put_nowait({"cmd": "WEATHER"})
    state.primary.normal_queue.put_nowait({"cmd": "WEATHER"})

    body = await _metrics_text()

    assert 'housepanel_transport_queue_depth{queue="interrupt"} 1' in body
    assert 'housepanel_transport_queue_depth{queue="normal"} 2' in body


@pytest.mark.asyncio
async def test_frame_send_advances_counter_and_timestamp():
    assert "housepanel_panel_last_frame_timestamp_seconds" not in await _metrics_text()

    state.record_frame_sent()
    body = await _metrics_text()

    assert "housepanel_panel_frames_sent_total 1" in body
    assert "housepanel_panel_last_frame_timestamp_seconds" in body
