import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from shared.models import UnifiedEvent
from aggregator.queue import TickerQueue


def _event(event_id: str = "e1", ttl: int = 60) -> UnifiedEvent:
    return UnifiedEvent(
        event_id=event_id, source="test", event_type="ticker",
        timestamp=datetime.now(timezone.utc), priority=1,
        ttl_seconds=ttl, payload={},
    )


@pytest.mark.asyncio
async def test_enqueue_and_dequeue():
    q = TickerQueue()
    await q.enqueue(_event("a"))
    result = await q.dequeue_non_expired()
    assert result is not None
    assert result.event_id == "a"


@pytest.mark.asyncio
async def test_dequeue_empty():
    q = TickerQueue()
    assert await q.dequeue_non_expired() is None


@pytest.mark.asyncio
async def test_ttl_expiry():
    q = TickerQueue()
    expired = UnifiedEvent(
        event_id="old", source="test", event_type="ticker",
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
        priority=1, ttl_seconds=60, payload={},
    )
    await q.enqueue(expired)
    assert await q.dequeue_non_expired() is None


@pytest.mark.asyncio
async def test_maxlen_overflow():
    import aggregator.queue as qmod
    original = qmod.TICKER_QUEUE_MAX_DEPTH
    qmod.TICKER_QUEUE_MAX_DEPTH = 3
    q = TickerQueue()
    for i in range(4):
        await q.enqueue(_event(str(i)))
    snapshot = await q.snapshot()
    assert len(snapshot) == 3
    qmod.TICKER_QUEUE_MAX_DEPTH = original


@pytest.mark.asyncio
async def test_snapshot_excludes_expired():
    q = TickerQueue()
    good = _event("good", ttl=60)
    expired = UnifiedEvent(
        event_id="exp", source="test", event_type="ticker",
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
        priority=1, ttl_seconds=60, payload={},
    )
    await q.enqueue(good)
    await q.enqueue(expired)
    snap = await q.snapshot()
    ids = [e.event_id for e in snap]
    assert "good" in ids
    assert "exp" not in ids
