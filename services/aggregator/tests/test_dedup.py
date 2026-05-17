import time
from aggregator.dedup import DedupCache
import aggregator.dedup as dmod


def test_not_duplicate_initially():
    d = DedupCache()
    assert d.is_duplicate("abc") is False


def test_duplicate_after_record():
    d = DedupCache()
    d.record("abc")
    assert d.is_duplicate("abc") is True


def test_expired_after_window():
    original = dmod.TICKER_DEDUP_WINDOW_SECONDS
    dmod.TICKER_DEDUP_WINDOW_SECONDS = 0
    d = DedupCache()
    d.record("xyz")
    time.sleep(0.01)
    assert d.is_duplicate("xyz") is False
    dmod.TICKER_DEDUP_WINDOW_SECONDS = original


def test_different_hashes_not_duplicate():
    d = DedupCache()
    d.record("hash1")
    assert d.is_duplicate("hash2") is False
