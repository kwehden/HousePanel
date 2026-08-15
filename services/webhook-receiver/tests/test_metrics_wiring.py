"""The recorder must be driven by the real forward path, not just exist."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webhook_receiver.forwarder import forward_to_aggregator, metrics
from webhook_receiver.main import metrics as metrics_endpoint


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.push_success_total = 0
    metrics.push_failure_total = 0
    metrics.last_push_success_wall = None
    yield


def _client(*, raises: Exception | None = None) -> MagicMock:
    client = AsyncMock()
    resp = MagicMock()
    resp.status_code = 202
    resp.raise_for_status = MagicMock(side_effect=raises)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_successful_forward_is_recorded():
    with patch("webhook_receiver.forwarder.httpx.AsyncClient", return_value=_client()):
        await forward_to_aggregator({"source": "webhook-receiver"})

    assert metrics.push_success_total == 1
    assert metrics.last_push_success_wall is not None


@pytest.mark.asyncio
async def test_failed_forward_is_recorded():
    """forward_to_aggregator swallows its exception, so the caller sees nothing;
    the metric is the only signal that a camera event was dropped."""
    client = _client(raises=RuntimeError("aggregator down"))
    with patch("webhook_receiver.forwarder.httpx.AsyncClient", return_value=client):
        await forward_to_aggregator({"source": "webhook-receiver"})

    assert metrics.push_failure_total == 1
    assert metrics.last_push_success_wall is None


@pytest.mark.asyncio
async def test_metrics_endpoint_declares_no_poll_interval():
    """Webhooks are event-driven: a staleness alert would fire on a quiet day."""
    body = (await metrics_endpoint()).body.decode()

    assert 'housepanel_source_push_total{outcome="success",service="webhook"} 0' in body
    assert "housepanel_source_poll_interval_seconds" not in body
