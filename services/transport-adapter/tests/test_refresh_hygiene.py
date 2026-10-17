"""Exercise real HTTPX stream ownership rather than mocked Response methods."""
import asyncio
import gc
import json
import weakref

import httpx
import pytest

from transport_adapter import state, state_refresh
from transport_adapter.stream_decompose import MAX_FRAME_BYTES, encode_frame


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body
        self.closed = False

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        self.closed = True


@pytest.fixture
def upstream(monkeypatch):
    original_client = httpx.AsyncClient
    replies = {"body": b"{}", "status": 200}
    streams, responses = [], []

    def respond(request):
        stream = ResponseStream(replies["body"])
        response = httpx.Response(replies["status"], stream=stream)
        streams.append(stream)
        responses.append(weakref.ref(response))
        return response

    def client(**kwargs):
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(state_refresh.httpx, "AsyncClient", client)
    monkeypatch.setattr(state, "normal_queue", asyncio.Queue(maxsize=50))
    return replies, streams, responses


def drain():
    frames = []
    while not state.normal_queue.empty():
        frames.append(state.normal_queue.get_nowait())
    return frames


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["x" * 1000, "\u754c" * 1000, '\\"' * 1000],
                         ids=["ascii", "multibyte", "json-escaped"])
@pytest.mark.parametrize("field", ["text", "narrative"])
async def test_snapshot_tickers_use_wire_budget_and_payload_ttl(upstream, text, field):
    replies, streams, _ = upstream
    replies["body"] = json.dumps({"ticker_queue": [
        {"event_id": "ticker-1", "payload": {field: text, "ttl_seconds": 120}},
    ]}).encode()
    await state_refresh._refresh_state("test")
    frames = drain()
    assert [frame["cmd"] for frame in frames] == ["TIME", "TICKER-APPEND"]
    assert text.startswith(frames[1]["text"])
    assert len(frames[1]["text"].encode()) <= 127
    assert all(len(encode_frame(frame).encode()) < MAX_FRAME_BYTES for frame in frames)
    assert frames[1]["ttl_seconds"] == 120
    assert all(stream.closed for stream in streams)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"[]", b"null", b"{bad", b'{"weather":{"temperature_c":20},"calendar":{"events":[42]}}',
    b'{"weather":{"temperature_c":"bad"}}', b'{"ticker_queue":[{"payload":{"text":42}}]}'])
async def test_invalid_snapshot_is_rejected_without_partial_replay(upstream, body):
    replies, streams, _ = upstream
    replies["body"] = body
    await state_refresh._refresh_state("test")
    assert [frame["cmd"] for frame in drain()] == ["TIME"]
    assert all(stream.closed for stream in streams)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "post"])
@pytest.mark.parametrize("status,body", [(200, b"{}"), (500, b"{}"), (200, b"{bad")])
async def test_refresh_responses_are_released_without_cyclic_gc(upstream, operation, status, body):
    replies, streams, responses = upstream
    replies.update(status=status, body=body)
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(50):
            if operation == "get":
                await state_refresh._refresh_state("test")
                drain()
            else:
                await state_refresh._trigger_poller_refresh()
        assert len(responses) == 50
        assert all(stream.closed for stream in streams)
        assert all(response() is None for response in responses)
    finally:
        if gc_was_enabled:
            gc.enable()


@pytest.mark.asyncio
async def test_refresh_http_error_is_not_logged_as_success(upstream, monkeypatch):
    replies, _, _ = upstream
    replies["status"] = 503
    events = []
    monkeypatch.setattr(state_refresh, "log_event", lambda logger, event, **kwargs: events.append(event))
    await state_refresh._trigger_poller_refresh()
    assert events == ["poller_refresh_trigger_failed"]
