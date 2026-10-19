"""Real bound streams must release their responses before cyclic GC runs."""
import asyncio
import gc
import gzip
import ssl
import weakref

import httpx
import pytest

from shared.http import async_request, request, ResponseTooLarge


@pytest.fixture
def no_gc():
    enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()
        gc.collect()


class Stream(httpx.SyncByteStream):
    def __init__(self, mode):
        self.mode, self.closes = mode, 0

    def __iter__(self):
        yield b"{" if self.mode == "invalid_json" else b'{}'
        if self.mode == "read_error":
            raise httpx.ReadError("interrupted body")
        if self.mode == "oversized":
            yield b"x" * 100

    def close(self):
        self.closes += 1
        if self.mode == "close_error":
            raise OSError("close failed")


class AsyncStream(httpx.AsyncByteStream):
    def __init__(self, mode):
        self.mode, self.closes = mode, 0

    async def __aiter__(self):
        yield b"{" if self.mode == "invalid_json" else b'{}'
        if self.mode == "read_error":
            raise httpx.ReadError("interrupted body")
        if self.mode == "cancelled":
            raise asyncio.CancelledError
        if self.mode == "oversized":
            yield b"x" * 100

    async def aclose(self):
        self.closes += 1
        await asyncio.sleep(0)
        if self.mode == "close_error":
            raise OSError("close failed")


def responder(stream_type, mode):
    refs, streams = [], []

    def respond(req):
        if mode == "connect_error":
            raise httpx.ConnectError("before headers")
        stream = stream_type(mode)
        response = httpx.Response(500 if mode == "http_error" else 200, stream=stream)
        refs.append(weakref.ref(response))
        streams.append(stream)
        return response
    return httpx.MockTransport(respond), refs, streams


MODES = ["success", "http_error", "invalid_json", "read_error", "oversized", "close_error", "connect_error"]


@pytest.mark.parametrize("mode", MODES)
def test_sync_lifetimes(mode, no_gc):
    transport, refs, streams = responder(Stream, mode)

    def invoke(client):
        try:
            response = request(client, "GET", "http://synthetic", max_bytes=32)
            response.raise_for_status()
            response.json()
        except (httpx.HTTPError, ValueError, OSError):
            assert mode != "success"
        else:
            assert mode == "success"

    with httpx.Client(transport=transport) as client:
        for _ in range(20):
            invoke(client)
    assert len(refs) == (0 if mode == "connect_error" else 20)
    assert all(stream.closes == 1 for stream in streams)
    assert all(ref() is None for ref in refs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES + ["cancelled"])
async def test_async_lifetimes(mode, no_gc):
    transport, refs, streams = responder(AsyncStream, mode)

    async def invoke(client):
        try:
            response = await async_request(client, "POST", "http://synthetic", max_bytes=32, json={"upload": "x" * 1000})
            response.raise_for_status()
            response.json()
        except (httpx.HTTPError, ValueError, OSError, asyncio.CancelledError):
            assert mode != "success"
        else:
            assert mode == "success"

    async with httpx.AsyncClient(transport=transport) as client:
        for _ in range(20):
            await invoke(client)
    # HTTPX's nested async iterators finalize on the next loop turn when a
    # size limit stops iteration early. This is not a cyclic-GC collection.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(refs) == (0 if mode == "connect_error" else 20)
    assert all(stream.closes == 1 for stream in streams)
    assert all(ref() is None for ref in refs)


@pytest.mark.asyncio
async def test_repeated_external_cancellation_joins_cleanup(no_gc):
    reading, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    refs = []

    class Blocking(AsyncStream):
        async def __aiter__(self):
            reading.set()
            await asyncio.Event().wait()
            yield b""

        async def aclose(self):
            self.closes += 1
            closing.set()
            await release.wait()

    stream = Blocking("success")
    def respond(req):
        response = httpx.Response(200, stream=stream)
        refs.append(weakref.ref(response))
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        task = asyncio.create_task(async_request(client, "GET", "http://synthetic"))
        await reading.wait()
        task.cancel()
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        del task
        await asyncio.sleep(0)
    assert stream.closes == 1
    assert all(ref() is None for ref in refs)


@pytest.mark.parametrize("status", [200, 503])
def test_body_budget_applies_to_decoded_bytes_and_error_preview(status):
    raw = b"x" * 1000
    def respond(req):
        return httpx.Response(status, headers={"Content-Encoding": "gzip"}, content=gzip.compress(raw))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if status == 200:
            with pytest.raises(ResponseTooLarge):
                request(client, "GET", "http://synthetic", max_bytes=500)
        else:
            response = request(client, "GET", "http://synthetic", max_bytes=500)
            assert len(response.content) == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_decoded_json_headers_and_request_are_preserved(asynchronous):
    def respond(req):
        return httpx.Response(200, headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
                              content=gzip.compress(b'{"ok":true}'))
    if asynchronous:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await async_request(client, "GET", "http://synthetic")
    else:
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            response = request(client, "GET", "http://synthetic")
    assert response.json() == {"ok": True}
    assert response.headers["content-encoding"] == "gzip"
    assert str(response.request.url) == "http://synthetic"
    assert response.is_closed


@pytest.mark.asyncio
async def test_invalid_budget_is_rejected_before_request():
    with httpx.Client() as client:
        with pytest.raises(ValueError, match="nonnegative"):
            request(client, "GET", "http://synthetic", max_bytes=-1)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="nonnegative"):
            await async_request(client, "GET", "http://synthetic", max_bytes=-1)


@pytest.mark.asyncio
async def test_real_connection_pools_and_ssl_contexts_release_without_gc(monkeypatch, no_gc):
    contexts, responses = [], []
    original = ssl.create_default_context

    def context(*args, **kwargs):
        result = original(*args, **kwargs)
        contexts.append(weakref.ref(result))
        return result

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def response_hook(response):
        responses.append(weakref.ref(response))

    monkeypatch.setattr(ssl, "create_default_context", context)
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        for _ in range(20):
            async with httpx.AsyncClient(trust_env=False, event_hooks={"response": [response_hook]}) as client:
                response = await async_request(client, "GET", url)
                assert response.json() == {}
            del client
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert len(contexts) == 20
    assert len(responses) == 20
    assert all(ref() is None for ref in responses)
    assert all(ref() is None for ref in contexts)
