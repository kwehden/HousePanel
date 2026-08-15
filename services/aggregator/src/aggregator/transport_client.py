from __future__ import annotations
from shared.logging import make_logger, log_event
from .dispatch_worker import DispatchWorker

logger = make_logger("aggregator")

_worker: DispatchWorker | None = None


def init_dispatch_worker(worker: DispatchWorker) -> None:
    global _worker
    _worker = worker


def get_dispatch_worker() -> DispatchWorker | None:
    return _worker


async def dispatch_command_to_transport(
    cmd: str, priority: int, payload: dict, event_id: str
) -> None:
    if _worker is None:
        log_event(logger, "dispatch_worker_not_ready", level="error", cmd=cmd, event_id=event_id)
        return
    _worker.enqueue(cmd, priority, payload, event_id)
