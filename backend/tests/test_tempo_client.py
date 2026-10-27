"""add-otel-tracing 4.1: TempoClient - found, not-found, and unreachable-server cases."""

from __future__ import annotations

import httpx
import pytest

from app.tempo.client import TempoClient, TempoError, TempoUnreachable


def transport_returning(status_code: int, json_body=None, *, text=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=json_body)

    return httpx.MockTransport(handler)


async def test_found_trace_returns_its_raw_json():
    body = {"batches": [{"spans": [{"name": "eval.generate"}]}]}
    client = TempoClient("http://tempo.example", transport=transport_returning(200, body))
    assert await client.get_trace("abc123") == body
    await client.aclose()


async def test_not_found_returns_none():
    client = TempoClient("http://tempo.example", transport=transport_returning(404, text="trace not found"))
    assert await client.get_trace("missing") is None
    await client.aclose()


async def test_unreachable_server_raises_tempo_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = TempoClient("http://tempo.example", transport=httpx.MockTransport(handler))
    with pytest.raises(TempoUnreachable):
        await client.get_trace("abc123")
    await client.aclose()


async def test_unexpected_status_raises_tempo_error():
    client = TempoClient("http://tempo.example", transport=transport_returning(500, text="internal error"))
    with pytest.raises(TempoError):
        await client.get_trace("abc123")
    await client.aclose()


async def test_non_json_200_response_raises_tempo_error():
    client = TempoClient("http://tempo.example", transport=transport_returning(200, text="not json"))
    with pytest.raises(TempoError):
        await client.get_trace("abc123")
    await client.aclose()


async def test_requests_the_expected_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"batches": []})

    client = TempoClient("http://tempo.example", transport=httpx.MockTransport(handler))
    await client.get_trace("deadbeef")
    assert seen["path"] == "/api/traces/deadbeef"
    await client.aclose()
