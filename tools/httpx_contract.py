"""Image-level HTTPX lifetime contracts: real service paths, no external network."""
import asyncio
from datetime import datetime, timezone
import gc
import json
import logging
import sys
import weakref
from unittest.mock import patch

import httpx

logging.disable(logging.CRITICAL)
OriginalAsyncClient = httpx.AsyncClient
OriginalClient = httpx.Client
logger = logging.getLogger("audit")


class AsyncStream(httpx.AsyncByteStream):
    def __init__(self, body, mode):
        self.body, self.mode, self.closed = body, mode, False

    async def __aiter__(self):
        yield self.body
        if self.mode == "read_error":
            raise httpx.ReadError("synthetic body failure")
        if self.mode == "cancelled":
            raise asyncio.CancelledError("synthetic cancellation")

    async def aclose(self):
        self.closed = True


class SyncStream(httpx.SyncByteStream):
    def __init__(self, body, mode):
        self.body, self.mode, self.closed = body, mode, False

    def __iter__(self):
        yield self.body
        if self.mode == "read_error":
            raise httpx.ReadError("synthetic body failure")

    def close(self):
        self.closed = True


async def audit(case, mode):
    refs, streams, outcomes = [], [], {}
    target_method = "POST" if case == "sysmon_post" else "GET"
    payload = {}
    if case == "calendar_get":
        payload = {"items": []}
    elif case == "google":
        payload = {"currentConditions": {"temperature": {"degrees": 21}}}
    elif case == "owm_current":
        payload = {"main": {"temp": 21}, "weather": [{"description": "clear"}]}
    elif case == "owm_forecast":
        payload = {"list": []}
    elif case == "wttr":
        payload = {"current_condition": [{"temp_C": "21", "humidity": "50",
                   "windspeedKmph": "0", "weatherDesc": [{"value": "clear"}]}],
                   "weather": [{"maxtempC": "22", "mintempC": "20"}]}

    def respond(request):
        target = not case.startswith("sysmon_") or request.method == target_method
        body = {"t": 21, "h": 50} if case.startswith("sysmon_") and request.method == "GET" else payload
        active_mode = mode if target else "success"
        raw = b"invalid JSON" if active_mode == "invalid_json" else json.dumps(body).encode()
        if active_mode == "oversized":
            raw = b"x" * (1024 * 1024 + 1)
        stream_type = SyncStream if case in ("calendar_get", "google", "owm_current", "owm_forecast", "wttr") else AsyncStream
        stream = stream_type(raw, active_mode)
        response = httpx.Response(500 if active_mode == "http_error" else 200, stream=stream)
        if target:
            refs.append(weakref.ref(response))
            streams.append(stream)
        return response

    transport = httpx.MockTransport(respond)
    def async_factory(**kwargs):
        return OriginalAsyncClient(transport=transport, **kwargs)
    def sync_factory(**kwargs):
        return OriginalClient(transport=transport, **kwargs)

    clients = []
    with patch.object(httpx, "AsyncClient", async_factory), patch.object(httpx, "Client", sync_factory):
        if case == "probe_scraper":
            from shared.http import async_request
            async def invoke():
                async with async_factory() as client:
                    response = await async_request(client, "GET", "http://synthetic/metrics")
                    response.raise_for_status()
        elif case.startswith("transport_"):
            from transport_adapter import state_refresh, state
            state.normal_queue = asyncio.Queue(maxsize=200)
            async def invoke():
                if case == "transport_post":
                    await state_refresh._trigger_poller_refresh()
                else:
                    await state_refresh._refresh_state("audit")
                while not state.normal_queue.empty():
                    state.normal_queue.get_nowait()
        elif case == "calendar_post":
            from calendar_poller.poller import push_calendar_update
            client = async_factory()
            clients.append(client)
            async def invoke():
                await push_calendar_update([], "http://synthetic", logger, client)
        elif case == "calendar_get":
            from calendar_poller.calendar_client import GoogleCalendarClient
            obj = GoogleCalendarClient.__new__(GoogleCalendarClient)
            obj._http_client = sync_factory()
            clients.append(obj._http_client)
            async def invoke():
                obj._fetch_from_calendar("synthetic", {}, {})
        elif case.startswith("sysmon_"):
            from sysmon_poller.main import _poll
            client = async_factory()
            clients.append(client)
            async def invoke():
                await _poll(client)
        elif case == "weather_post":
            from weather_poller.poller import push_weather_update
            from shared.models import WeatherConditions
            weather = WeatherConditions(provider="audit", timestamp=datetime.now(timezone.utc), temperature_c=21, conditions="clear")
            client = async_factory()
            clients.append(client)
            async def invoke():
                await push_weather_update(weather, "http://synthetic", logger, client)
        elif case in ("google", "owm_current", "owm_forecast", "wttr"):
            if case == "google":
                from weather_poller.adapters.google import GoogleWeatherAdapter
                obj = GoogleWeatherAdapter("synthetic", "0,0")
            elif case.startswith("owm_"):
                from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter
                obj = OpenWeatherMapAdapter("synthetic", "synthetic")
                if case == "owm_current":
                    obj._fetch_forecast = lambda: []
            else:
                from weather_poller.adapters.wttr_in import WttrInAdapter
                obj = WttrInAdapter("synthetic")
            clients.append(obj._client)
            async def invoke():
                (obj._fetch_forecast if case == "owm_forecast" else obj.fetch_current)()
        elif case in ("webhook_post", "ring_post"):
            if case == "webhook_post":
                from webhook_receiver.forwarder import forward_to_aggregator
            else:
                from ring_integration.main import forward_to_aggregator
            async def invoke():
                await forward_to_aggregator({"synthetic": True})
        elif case == "aggregator_refresh":
            from aggregator.routes import internal_refresh
            async def invoke():
                await internal_refresh()
                await asyncio.sleep(0)
        elif case == "aggregator_dispatch":
            from aggregator.dispatch_worker import DispatchWorker
            async def invoke():
                worker = DispatchWorker("http://synthetic")
                worker.enqueue("SYSMON-UPDATE", 0, {"temp_c": 21}, "audit")
                await worker._run_once()
        else:
            raise ValueError(case)

        gc.collect()
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            for _ in range(20):
                try:
                    await invoke()
                    name = "returned"
                except BaseException as exc:
                    name = type(exc).__name__
                outcomes[name] = outcomes.get(name, 0) + 1
            await asyncio.sleep(0)
            alive_before = sum(ref() is not None for ref in refs)
            closed = sum(stream.closed for stream in streams)
            gc.collect()
            alive_after = sum(ref() is not None for ref in refs)
        finally:
            if was_enabled:
                gc.enable()
            for client in clients:
                if isinstance(client, OriginalAsyncClient):
                    await client.aclose()
                else:
                    client.close()
    return {"case": case, "mode": mode, "requests": len(refs), "streams_closed": closed,
            "responses_alive_before_gc": alive_before, "responses_alive_after_gc": alive_after,
            "outcomes": outcomes, "python": sys.version.split()[0], "httpx": httpx.__version__}


async def main():
    cases = {
        "aggregator": ["aggregator_dispatch", "aggregator_refresh"],
        "calendar-poller": ["calendar_get", "calendar_post", "probe_scraper"],
        "sysmon-poller": ["sysmon_get", "sysmon_post"],
        "transport-adapter": ["transport_get", "transport_post"],
        "weather-poller": ["google", "owm_current", "owm_forecast", "wttr", "weather_post"],
        "webhook-receiver": ["webhook_post"],
        "ring-integration": ["ring_post"],
    }
    for case in cases[sys.argv[1]]:
        modes = ["success", "http_error", "invalid_json", "read_error", "oversized"]
        if case not in ("calendar_get", "google", "owm_current", "owm_forecast", "wttr"):
            modes.append("cancelled")
        for mode in modes:
            result = await audit(case, mode)
            assert result["requests"] >= 20, result
            assert result["streams_closed"] == result["requests"], result
            assert result["responses_alive_before_gc"] == 0, result
            assert result["responses_alive_after_gc"] == 0, result
            if mode == "success":
                assert result["outcomes"] == {"returned": 20}, result
            if mode == "cancelled":
                assert result["outcomes"] == {"CancelledError": 20}, result
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

