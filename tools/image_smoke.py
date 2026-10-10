"""Check packaged app imports, startup, routes, and shutdown without credentials."""
import importlib
import sys
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


service = sys.argv[1]
module = importlib.import_module(service.replace("-", "_") + ".main")
with ExitStack() as stack:
    if service == "calendar-poller":
        stack.enter_context(patch.object(module, "GoogleCalendarClient", return_value=MagicMock()))
        stack.enter_context(patch.object(module, "poll_google_calendar", new=AsyncMock()))
    elif service == "weather-poller":
        stack.enter_context(patch.object(module, "poll_weather", new=AsyncMock()))
    elif service == "sysmon-poller":
        stack.enter_context(patch.object(module, "_poll", new=AsyncMock()))
    with TestClient(module.app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/metrics").status_code == 200
        if service in ("calendar-poller", "weather-poller"):
            assert client.post("/internal/poll-now").status_code == 202
print(f"{service}: startup, health, metrics, shutdown passed")
