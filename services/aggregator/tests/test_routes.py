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
