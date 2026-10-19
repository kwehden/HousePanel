"""Bounded HTTPX requests that release response/stream cycles without GC."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 1024 * 1024
ERROR_PREVIEW_BYTES = 200


class ResponseTooLarge(ValueError):
    """The decoded upstream body exceeds the caller's allocation budget."""


def _append(body: bytearray, chunk: bytes, limit: int, truncate: bool) -> bool:
    remaining = limit - len(body)
    if len(chunk) > remaining and not truncate:
        raise ResponseTooLarge(f"HTTP response exceeds {limit} bytes")
    body.extend(chunk[:remaining])
    return truncate and len(body) == limit


def _limits(response: httpx.Response, max_bytes: int) -> tuple[int, bool]:
    if response.status_code >= 300:
        return min(max_bytes, ERROR_PREVIEW_BYTES), True
    return max_bytes, False


def _buffered(response: httpx.Response, body: bytearray) -> httpx.Response:
    # Construct the decoded body before restoring headers, avoiding a second
    # Content-Encoding decode. Do not copy transport-owned network_stream data.
    result = httpx.Response(response.status_code, content=bytes(body), request=response.request)
    result.headers = response.headers.copy()
    return result


def request(client: httpx.Client, method: str, url: str, *,
            max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any) -> httpx.Response:
    if max_bytes < 0:
        raise ValueError("max_bytes must be nonnegative")
    with client.stream(method, url, **kwargs) as response:
        try:
            limit, truncate = _limits(response, max_bytes)
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=min(16384, max(1, limit))):
                if _append(body, chunk, limit, truncate):
                    break
            return _buffered(response, body)
        finally:
            try:
                response.close()
            finally:
                response.stream = httpx.ByteStream(b"")


async def _close(response: httpx.Response) -> None:
    # Join the owned close task even if cancellation arrives during cleanup.
    closing = asyncio.create_task(response.aclose())
    cancelled = False
    try:
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                cancelled = True
        closing.result()
    finally:
        response.stream = httpx.ByteStream(b"")
    if cancelled:
        raise asyncio.CancelledError


async def async_request(client: httpx.AsyncClient, method: str, url: str, *,
                        max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any) -> httpx.Response:
    if max_bytes < 0:
        raise ValueError("max_bytes must be nonnegative")
    async with client.stream(method, url, **kwargs) as response:
        try:
            limit, truncate = _limits(response, max_bytes)
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=min(16384, max(1, limit))):
                if _append(body, chunk, limit, truncate):
                    break
            return _buffered(response, body)
        finally:
            await _close(response)
