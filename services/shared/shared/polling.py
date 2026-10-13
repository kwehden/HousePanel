"""Coalesce scheduled and manual refreshes into one owned polling task."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable


class PollRunner:
    def __init__(self, poll: Callable[[], Awaitable[None]], logger: logging.Logger):
        self._poll = poll
        self._logger = logger
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def request(self) -> None:
        if not self._closed and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await self._poll()
        except Exception:
            self._logger.exception("poll_failed")

    async def run(self) -> None:
        self.request()
        if self._task is not None:
            await asyncio.shield(self._task)

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            # A cancelled to_thread await does not stop its worker. Let the
            # poll finish before its HTTP clients are closed by the lifespan.
            await asyncio.shield(self._task)
            self._task = None
