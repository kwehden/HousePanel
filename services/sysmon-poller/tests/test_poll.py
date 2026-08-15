"""Tests for the sysmon-poller polling cycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sysmon_poller.main import _poll, healthz


def _make_client(
    *,
    latest_status: int = 200,
    latest_json: dict | None = None,
    agg_status: int = 202,
) -> MagicMock:
    """An httpx.AsyncClient double covering the /latest GET and aggregator POST."""
    client = AsyncMock()

    latest = MagicMock()
    latest.status_code = latest_status
    latest.json = MagicMock(
        return_value={"t": 31.5, "h": 44.0} if latest_json is None else latest_json
    )
    client.get = AsyncMock(return_value=latest)

    posted = MagicMock()
    posted.status_code = agg_status
    client.post = AsyncMock(return_value=posted)

    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def _run(client: MagicMock) -> None:
    with patch("sysmon_poller.main.httpx.AsyncClient", return_value=client):
        await _poll()


@pytest.mark.asyncio
async def test_successful_poll_forwards_reading_to_aggregator() -> None:
    client = _make_client()

    await _run(client)

    client.post.assert_awaited_once()
    body = client.post.await_args.kwargs["json"]
    assert body["source"] == "sysmon-poller"
    assert body["event_type"] == "sysmon-update"
    assert body["priority"] == 0
    assert body["ttl_seconds"] == 90
    assert body["payload"]["temp_c"] == 31.5
    assert body["payload"]["humidity_pct"] == 44.0


@pytest.mark.asyncio
async def test_poll_queries_latest_for_the_configured_board() -> None:
    client = _make_client()

    await _run(client)

    assert client.get.await_args.args[0].endswith("/latest")
    assert "board_id" in client.get.await_args.kwargs["params"]


@pytest.mark.asyncio
async def test_readings_are_coerced_to_float() -> None:
    """ardtemp returns JSON numbers as strings on some firmware revisions."""
    client = _make_client(latest_json={"t": "31.5", "h": "44.0"})

    await _run(client)

    payload = client.post.await_args.kwargs["json"]["payload"]
    assert payload["temp_c"] == 31.5
    assert payload["humidity_pct"] == 44.0


@pytest.mark.asyncio
@pytest.mark.parametrize("latest_json", [{"t": 31.5, "h": None}, {"t": 31.5}])
async def test_absent_humidity_is_forwarded_as_none(latest_json: dict) -> None:
    """The filament box is optional — a missing sensor must not block the temp."""
    client = _make_client(latest_json=latest_json)

    await _run(client)

    payload = client.post.await_args.kwargs["json"]["payload"]
    assert payload["humidity_pct"] is None
    assert payload["temp_c"] == 31.5


@pytest.mark.asyncio
async def test_non_200_from_ardtemp_skips_the_post() -> None:
    client = _make_client(latest_status=503)

    await _run(client)

    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_error_payload_skips_the_post() -> None:
    """ardtemp answers 200 with {"error": ...} when a board has never reported.

    The reading is deliberately well-formed here: with only the error key the
    post is skipped anyway because `latest["t"]` raises, so the test would pass
    without the guard actually being exercised.
    """
    client = _make_client(latest_json={"error": "no data for board", "t": 31.5})

    await _run(client)

    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_reading_does_not_raise() -> None:
    """A reading with no temperature must be swallowed, not kill the job."""
    client = _make_client(latest_json={"h": 44.0})

    await _run(client)

    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("agg_status", [200, 202, 204])
async def test_aggregator_success_codes_are_accepted(agg_status: int) -> None:
    """The aggregator answers 202 Accepted; treating that as failure caused a
    spurious warning on every successful poll."""
    client = _make_client(agg_status=agg_status)

    with patch("sysmon_poller.main.log_event") as log:
        await _run(client)

    events = [call.args[1] for call in log.call_args_list]
    assert "poll_success" in events
    assert "aggregator_post_failed" not in events


@pytest.mark.asyncio
async def test_aggregator_rejection_is_logged_not_raised() -> None:
    client = _make_client(agg_status=500)

    with patch("sysmon_poller.main.log_event") as log:
        await _run(client)

    events = [call.args[1] for call in log.call_args_list]
    assert "aggregator_post_failed" in events
    assert "poll_success" not in events


@pytest.mark.asyncio
async def test_network_error_is_contained() -> None:
    """The scheduler job must survive an unreachable ardtemp."""
    client = _make_client()
    client.get = AsyncMock(side_effect=OSError("connection refused"))

    with patch("sysmon_poller.main.log_event") as log:
        await _run(client)  # must not raise

    assert "poll_error" in [call.args[1] for call in log.call_args_list]


@pytest.mark.asyncio
async def test_healthz() -> None:
    assert await healthz() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Metric wiring — poll and push outcomes must be recorded separately
# ---------------------------------------------------------------------------

from sysmon_poller.main import metrics  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.poll_success_total = 0
    metrics.poll_failure_total = 0
    metrics.push_success_total = 0
    metrics.push_failure_total = 0
    metrics.last_poll_success_wall = None
    metrics.last_push_success_wall = None
    yield


@pytest.mark.asyncio
async def test_successful_cycle_records_poll_and_push() -> None:
    await _run(_make_client())

    assert metrics.poll_success_total == 1
    assert metrics.push_success_total == 1


@pytest.mark.asyncio
async def test_aggregator_rejection_records_push_failure_only() -> None:
    """The board was read fine — only delivery failed, and the split matters:
    it distinguishes a dead sensor from a dead aggregator."""
    await _run(_make_client(agg_status=500))

    assert metrics.poll_success_total == 1
    assert metrics.push_failure_total == 1
    assert metrics.push_success_total == 0


@pytest.mark.asyncio
async def test_unreachable_board_records_poll_failure_only() -> None:
    client = _make_client()
    client.get = AsyncMock(side_effect=OSError("connection refused"))

    await _run(client)

    assert metrics.poll_failure_total == 1
    assert metrics.push_success_total == 0
    assert metrics.push_failure_total == 0


@pytest.mark.asyncio
async def test_non_200_from_board_records_a_poll_failure() -> None:
    """Mutation testing found record_poll(False) here could flip to True
    unnoticed — a dead board would have counted as a healthy poll."""
    await _run(_make_client(latest_status=503))

    assert metrics.poll_failure_total == 1
    assert metrics.poll_success_total == 0


@pytest.mark.asyncio
async def test_error_payload_records_a_poll_failure() -> None:
    await _run(_make_client(latest_json={"error": "no data", "t": 31.5}))

    assert metrics.poll_failure_total == 1
    assert metrics.poll_success_total == 0
