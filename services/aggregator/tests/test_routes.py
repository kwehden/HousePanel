from __future__ import annotations
import pytest
from aggregator.dispatch_worker import DispatchWorker
from aggregator.queue import TickerQueue
from aggregator.dedup import DedupCache
from aggregator.state import AggregatorState
from aggregator.routes import init_singletons, internal_health
from aggregator.transport_client import init_dispatch_worker


@pytest.mark.asyncio
async def test_health_reports_dispatch_queue_and_circuit():
    """The dispatch queue is the one that carries panel updates — an outage
    that jams it must be visible here, not just in the ticker queue."""
    init_singletons(TickerQueue(), DedupCache(), AggregatorState())
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    init_dispatch_worker(worker)

    worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id="ev-1")
    worker.enqueue("DOORBELL", priority=99, payload={}, event_id="ev-2")

    health = await internal_health()

    assert health["status"] == "ok"
    assert health["queue_depth"] == 0          # ticker queue, unaffected
    assert health["dispatch_queue_depth"] == 2
    assert health["dispatch_circuit"] == "closed"


@pytest.mark.asyncio
async def test_health_reports_open_circuit():
    init_singletons(TickerQueue(), DedupCache(), AggregatorState())
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    init_dispatch_worker(worker)

    worker._circuit._failure_threshold = 1
    worker._circuit.record_failure()

    health = await internal_health()

    # Reported, not fatal: readiness stays ok so the aggregator keeps
    # accepting events from the pollers while the panel link is down.
    assert health["dispatch_circuit"] == "open"
    assert health["status"] == "ok"


# ---------------------------------------------------------------------------
# /metrics — the functional probe
# ---------------------------------------------------------------------------

async def _metrics_text() -> str:
    from aggregator.routes import metrics
    resp = await metrics()
    return resp.body.decode()


@pytest.mark.asyncio
async def test_metrics_exposes_queue_and_circuit():
    init_singletons(TickerQueue(), DedupCache(), AggregatorState())
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    init_dispatch_worker(worker)
    worker.enqueue("SYSMON-UPDATE", priority=0, payload={}, event_id="ev-1")

    body = await _metrics_text()

    assert "housepanel_dispatch_queue_depth 1" in body
    assert "housepanel_dispatch_queue_max 200" in body
    assert 'housepanel_dispatch_circuit_state{state="closed"} 1' in body
    assert 'housepanel_dispatch_circuit_state{state="open"} 0' in body


@pytest.mark.asyncio
async def test_last_success_absent_until_first_delivery():
    """Absent, not zero — otherwise the staleness alert fires on cold start."""
    init_singletons(TickerQueue(), DedupCache(), AggregatorState())
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    init_dispatch_worker(worker)

    body = await _metrics_text()
    assert "housepanel_dispatch_last_success_timestamp_seconds" not in body

    worker.last_success_wall = 1755273600.0
    body = await _metrics_text()
    assert "housepanel_dispatch_last_success_timestamp_seconds 1755273600" in body


@pytest.mark.asyncio
async def test_metrics_counts_outcomes():
    init_singletons(TickerQueue(), DedupCache(), AggregatorState())
    worker = DispatchWorker(transport_url="http://test-transport:8002")
    init_dispatch_worker(worker)
    worker.dispatched_total = 7
    worker.failed_total = 2
    worker.expired_total = 5
    worker.rejected_total = 1

    body = await _metrics_text()

    assert 'housepanel_dispatch_commands_total{outcome="dispatched"} 7' in body
    assert 'housepanel_dispatch_commands_total{outcome="failed"} 2' in body
    assert 'housepanel_dispatch_commands_total{outcome="expired"} 5' in body
    assert 'housepanel_dispatch_commands_total{outcome="rejected"} 1' in body
