from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from transport_adapter import state
from transport_adapter.state_refresh import handle_hello_frame


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


_AGGREGATOR_STATE = {
    "weather": {
        "provider": "google",
        "timestamp": "2026-05-17T00:00:00Z",
        "temperature_c": 18.5,
        "conditions": "Partly Cloudy",
        "humidity_pct": 60.0,
        "wind_speed_ms": 3.2,
        "icon_code": "partly-cloudy",
    },
    "calendar": {
        "poll_timestamp": "2026-05-17T00:00:00Z",
        "events": [
            {
                "event_id": "evt-1",
                "summary": "Team standup",
                "start": "2026-05-17T09:00:00",
                "end": "2026-05-17T09:30:00",
                "all_day": False,
            }
        ],
    },
    "ticker_queue": [],
}


@pytest.mark.asyncio
async def test_hello_frame_enqueues_weather_and_calendar():
    """On HELLO, state_refresh puts WEATHER-UPDATE and CALENDAR-UPDATE in normal_queue."""
    mock_response = MagicMock()
    mock_response.json.return_value = _AGGREGATOR_STATE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("transport_adapter.state_refresh.httpx.AsyncClient", return_value=mock_client):
        await handle_hello_frame({"cmd": "HELLO", "firmware_version": "1.0.0", "post_ota": False})

    queued = []
    while not state.normal_queue.empty():
        queued.append(state.normal_queue.get_nowait())

    cmds = [q["cmd"] for q in queued]
    assert "TIME" in cmds, f"TIME not enqueued; got {cmds}"
    assert "WEATHER-UPDATE" in cmds, f"WEATHER-UPDATE not enqueued; got {cmds}"
    assert "CALENDAR-UPDATE" in cmds, f"CALENDAR-UPDATE not enqueued; got {cmds}"

    time_cmd = next(q for q in queued if q["cmd"] == "TIME")
    assert "epoch" in time_cmd, "TIME command missing epoch"
    assert "utc_offset_min" in time_cmd, "TIME command missing utc_offset_min"
    assert isinstance(time_cmd["epoch"], int) and time_cmd["epoch"] > 0
    assert cmds.index("TIME") == 0, "TIME must be first in the queue"

    weather_cmd = next(q for q in queued if q["cmd"] == "WEATHER-UPDATE")
    assert weather_cmd["temperature_c"] == 18.5
    assert weather_cmd["conditions"] == "Partly Cloudy"
    assert "message_id" in weather_cmd

    calendar_cmd = next(q for q in queued if q["cmd"] == "CALENDAR-UPDATE")
    assert len(calendar_cmd["events"]) == 1
    assert calendar_cmd["events"][0]["summary"] == "Team standup"
    assert "message_id" in calendar_cmd
