"""Exercise real weather parsing, fallback, and pushes against loopback HTTP."""
import argparse
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from weather_poller.adapters.wttr_in import WttrInAdapter
from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter
from weather_poller.poller import WeatherPollerState, metrics, poll_weather
from shared.polling import PollRunner


async def probe(cycles):
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    count = 0

    async def respond(reader, writer):
        nonlocal count
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                for line in header.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        await reader.readexactly(int(line.split(b":", 1)[1]))
                status = b"200 OK"
                if b"/wttr " in header:
                    count += 1
                    if count % 17 == 0:
                        status = b"503 Unavailable"
                    payload = {"current_condition": [{"temp_C": "20", "humidity": "50",
                        "windspeedKmph": "10", "weatherDesc": [{"value": "Clear"}]}],
                        "weather": [{"maxtempC": "22", "mintempC": "10"}]}
                elif b"/owm " in header:
                    payload = {"main": {"temp": 20}, "weather": [{"description": "clear"}], "list": []}
                else:
                    payload = {"accepted": True}
                body = json.dumps(payload).encode()
                writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: " +
                             str(len(body)).encode() + b"\r\n\r\n" + body)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    primary, fallback = WttrInAdapter("synthetic"), OpenWeatherMapAdapter("fake", "synthetic")
    primary._client.event_hooks["request"] = [lambda r: setattr(r, "url", httpx.URL(base + "/wttr"))]
    fallback._client.event_hooks["request"] = [lambda r: setattr(r, "url", httpx.URL(base + "/owm"))]
    state = WeatherPollerState()
    logger = logging.getLogger("probe")
    try:
        async with server, httpx.AsyncClient() as http:
            runner = PollRunner(lambda: poll_weather(primary, fallback, state, base, logger, http), logger)
            try:
                for cycle in range(1, cycles + 1):
                    await runner.run()
                    if cycle % 500 == 0:
                        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
                        print(json.dumps({"cycle": cycle, "rss_kib": int(status["VmRSS"].split()[0]),
                            "fds": len(list(Path("/proc/self/fd").iterdir())),
                            "threads": int(status["Threads"]), "tasks": len(asyncio.all_tasks())}), flush=True)
            finally:
                await runner.close()
                # Close synchronous pools before waiting for the server's clients.
                primary.close()
                fallback.close()
            assert metrics.poll_success_total == cycles
            assert metrics.push_success_total == cycles
            assert count == cycles
    finally:
        primary.close()
        fallback.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3000)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(probe(args.cycles))
