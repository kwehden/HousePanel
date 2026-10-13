import asyncio

from shared.body_limit import BodyLimitMiddleware


def test_chunked_body_is_rejected_before_application_runs():
    called = False
    sent = []
    chunks = iter([
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False}])

    async def application(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    asyncio.run(BodyLimitMiddleware(application, max_bytes=5)({"type": "http"}, receive, send))
    assert not called
    assert sent[0]["status"] == 413


def test_body_at_the_limit_is_replayed_exactly_once():
    chunks = iter([
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"de", "more_body": False},
        {"type": "http.disconnect"}])

    async def receive():
        return next(chunks)

    async def application(scope, receive, send):
        assert await receive() == {"type": "http.request", "body": b"abcde", "more_body": False}
        assert await receive() == {"type": "http.disconnect"}

    async def send(message):
        pass

    asyncio.run(BodyLimitMiddleware(application, max_bytes=5)({"type": "http"}, receive, send))


def test_websockets_bypass_http_body_buffering():
    called = False
    async def application(scope, receive, send):
        nonlocal called
        called = True
    asyncio.run(BodyLimitMiddleware(application)({"type": "websocket"}, None, None))
    assert called


def test_disconnected_request_does_not_run_application():
    async def receive():
        return {"type": "http.disconnect"}
    async def application(scope, receive, send):
        raise AssertionError("disconnected request reached the app")
    asyncio.run(BodyLimitMiddleware(application)({"type": "http"}, receive, None))
