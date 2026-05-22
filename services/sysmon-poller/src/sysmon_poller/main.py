from __future__ import annotations

import os
import time as _time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from shared.logging import make_logger, log_event

logger = make_logger("sysmon-poller")

_ARDTEMP_URL   = os.environ.get("ARDTEMP_URL",    "http://ardtemp-service.ardtemp.svc.cluster.local:8000")
_AGGREGATOR_URL = os.environ.get("AGGREGATOR_URL", "http://housepanel-aggregator:8001")
_BOARD_ID       = os.environ.get("ARDTEMP_BOARD_ID", "r4wifi")
_LABEL          = os.environ.get("ARDTEMP_LABEL",    "CPU Rad Intake")
_POLL_INTERVAL  = int(os.environ.get("SYSMON_POLL_INTERVAL_SECONDS", "30"))
_HISTORY_WINDOW = int(os.environ.get("SYSMON_HISTORY_WINDOW_SECONDS", "3600"))


async def _poll() -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            latest_resp = await client.get(
                f"{_ARDTEMP_URL}/latest", params={"board_id": _BOARD_ID}
            )
            if latest_resp.status_code != 200:
                log_event(logger, "poll_failed", level="warning",
                          status=latest_resp.status_code)
                return
            latest = latest_resp.json()
            if "error" in latest:
                log_event(logger, "poll_no_data", level="warning", board_id=_BOARD_ID)
                return

            temp_c = float(latest["t"])

            since = int(_time.time()) - _HISTORY_WINDOW
            hist_resp = await client.get(
                f"{_ARDTEMP_URL}/readings",
                params={"board_id": _BOARD_ID, "since": since, "limit": 20},
            )
            history: list[float] = []
            if hist_resp.status_code == 200:
                history = [round(float(r["t"]), 1) for r in hist_resp.json()]

            agg_resp = await client.post(
                f"{_AGGREGATOR_URL}/internal/events",
                json={
                    "source": "sysmon-poller",
                    "event_type": "sysmon-update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "priority": 0,
                    "payload": {
                        "temp_c": temp_c,
                        "history": history,
                        "board_id": _BOARD_ID,
                        "label": _LABEL,
                    },
                    "ttl_seconds": 90,
                },
            )
            if agg_resp.status_code not in (200, 204):
                log_event(logger, "aggregator_post_failed", level="warning",
                          status=agg_resp.status_code)
                return
            log_event(logger, "poll_success", temp_c=temp_c, history_count=len(history))
    except Exception as exc:
        log_event(logger, "poll_error", level="warning", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _poll,
        trigger="interval",
        seconds=_POLL_INTERVAL,
        id="poll_sysmon",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    log_event(logger, "scheduler_started",
              board_id=_BOARD_ID, poll_interval_seconds=_POLL_INTERVAL)
    yield
    scheduler.shutdown(wait=False)
    log_event(logger, "scheduler_stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("sysmon_poller.main:app", host="0.0.0.0", port=8005)
