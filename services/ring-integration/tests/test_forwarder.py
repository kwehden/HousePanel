"""Tests for ring_integration.main.forward_to_aggregator."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("AGGREGATOR_URL", "http://mock-aggregator:8001")

from ring_integration.main import forward_to_aggregator

EVENT_DATA = {
    "source": "ring",
    "event_type": "doorbell-interrupt",
    "timestamp": "2026-05-17T10:00:00+00:00",
    "priority": 99,
    "payload": {
        "device_id": "12345",
        "device_name": "Front Door",
        "event_id": "abc-123",
    },
}


@pytest.mark.asyncio
async def test_forward_success_posts_to_correct_url() -> None:
    """Successful forward: POST is made to the aggregator /internal/events URL."""
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ring_integration.main.httpx.AsyncClient", return_value=mock_client):
        await forward_to_aggregator(EVENT_DATA)

    mock_client.post.assert_awaited_once_with(
        "http://mock-aggregator:8001/internal/events",
        json=EVENT_DATA,
    )


@pytest.mark.asyncio
async def test_forward_timeout_does_not_propagate() -> None:
    """TimeoutException must be caught; the coroutine must complete without raising."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=MagicMock())
    )

    with patch("ring_integration.main.httpx.AsyncClient", return_value=mock_client):
        # Must not raise
        await forward_to_aggregator(EVENT_DATA)


@pytest.mark.asyncio
async def test_forward_http_error_does_not_propagate() -> None:
    """HTTP error responses must be caught; the coroutine must complete without raising."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("ring_integration.main.httpx.AsyncClient", return_value=mock_client):
        await forward_to_aggregator(EVENT_DATA)
