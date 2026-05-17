from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta

TICKER_DEDUP_WINDOW_SECONDS = int(os.environ.get("TICKER_DEDUP_WINDOW_SECONDS", "30"))


class DedupCache:
    def __init__(self) -> None:
        self._cache: dict[str, datetime] = {}

    def _evict_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self._cache = {k: v for k, v in self._cache.items() if v > now}

    def is_duplicate(self, dedup_hash: str) -> bool:
        self._evict_expired()
        return dedup_hash in self._cache

    def record(self, dedup_hash: str) -> None:
        self._evict_expired()
        expiry = datetime.now(timezone.utc) + timedelta(seconds=TICKER_DEDUP_WINDOW_SECONDS)
        self._cache[dedup_hash] = expiry
