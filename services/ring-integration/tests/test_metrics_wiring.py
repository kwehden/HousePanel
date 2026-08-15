"""The recorder must be driven by the real forward path, not just exist."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ring_integration import main as ring_main


@pytest.fixture(autouse=True)
def _reset_metrics():
    ring_main.metrics.push_success_total = 0
    ring_main.metrics.push_failure_total = 0
    ring_main.metrics.last_push_success_wall = None
    ring_main._ring_connected = False
    yield


def _client(*, raises: Exception | None = None) -> MagicMock:
    client = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=raises)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_successful_forward_is_recorded():
    with patch("ring_integration.main.httpx.AsyncClient", return_value=_client()):
        await ring_main.forward_to_aggregator({"payload": {"event_id": "e1"}})

    assert ring_main.metrics.push_success_total == 1


@pytest.mark.asyncio
async def test_failed_forward_is_recorded():
    """A dropped doorbell press is invisible otherwise — the forward swallows."""
    client = _client(raises=RuntimeError("aggregator down"))
    with patch("ring_integration.main.httpx.AsyncClient", return_value=client):
        await ring_main.forward_to_aggregator({"payload": {"event_id": "e1"}})

    assert ring_main.metrics.push_failure_total == 1
    assert ring_main.metrics.last_push_success_wall is None


@pytest.mark.asyncio
async def test_connection_gauge_tracks_listener_state():
    """Connection loss is the Ring failure worth alerting on, not silence."""
    assert "housepanel_ring_connected 0" in (await ring_main.metrics_endpoint()).body.decode()

    ring_main._ring_connected = True
    assert "housepanel_ring_connected 1" in (await ring_main.metrics_endpoint()).body.decode()


@pytest.mark.asyncio
async def test_no_poll_interval_declared():
    body = (await ring_main.metrics_endpoint()).body.decode()
    assert "housepanel_source_poll_interval_seconds" not in body
