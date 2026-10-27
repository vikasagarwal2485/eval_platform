"""Tests for the standalone agent SDK (agents/eval_agent_sdk). Imported via a sys.path insert rather than a
package install, since it is a separate, dependency-light package meant to run inside a *deployed agent's*
process, not inside the platform backend."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

from eval_agent_sdk import AgentClient, whoami  # noqa: E402


def _client(handler, **kwargs) -> AgentClient:
    transport = httpx.MockTransport(handler)
    return AgentClient("http://platform.local", "tok", transport=transport, flush_interval_s=0.05, **kwargs)


def test_turn_sends_start_and_end():
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.extend(request.read() and __import__("json").loads(request.content))
        return httpx.Response(202, json={"accepted": len(received), "duplicates": 0, "rejected": []})

    client = _client(handler)
    with client.turn("s1", input="hello") as t:
        t.llm_call(model="qwen3:8b", output="hi there", prompt_tokens=10, completion_tokens=3)
        t.finish("hi there")
    client.close(timeout_s=2.0)

    types = [e["type"] for e in received]
    assert types == ["turn.start", "turn.end"]  # add-otel-tracing: no more "span" event type
    end = next(e for e in received if e["type"] == "turn.end")
    assert end["status"] == "ok"
    assert end["output"] == "hi there"
    assert end["models"] == ["qwen3:8b"]
    assert end["prompt_tokens"] == 10 and end["completion_tokens"] == 3
    assert end["cost"] is None  # qwen3:8b has no price-list entry - never fabricated as 0
    assert end["trace_id"] is None  # no otel_endpoint configured on this client


def test_exception_inside_turn_is_recorded_as_error_and_reraised():
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0, "rejected": []})

    client = _client(handler)
    try:
        with client.turn("s1", input="hello") as t:
            t.llm_call(model="qwen3:8b", output="")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    else:
        raise AssertionError("the agent's own exception must propagate")
    client.close(timeout_s=2.0)

    end = next(e for e in received if e["type"] == "turn.end")
    assert end["status"] == "error"


def test_platform_unreachable_never_blocks_or_raises_into_the_agent():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("platform is down", request=request)

    client = _client(handler, max_attempts=1)
    started = time.monotonic()
    with client.turn("s1", input="hello") as t:
        t.finish("ok")
    elapsed = time.monotonic() - started
    assert elapsed < 1.0  # emitting events never waits on the network
    client.close(timeout_s=1.0)  # must not raise even though every send failed


def test_sustained_overload_drops_oldest_and_counts_drops():
    started = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        started.wait()  # the background sender is blocked "in flight" while the main thread floods the queue
        return httpx.Response(202, json={"accepted": 0, "duplicates": 0, "rejected": []})

    # A tiny queue and a slow-to-respond transport forces backpressure quickly.
    client = _client(handler, max_queue=3, batch_size=1)
    for i in range(10):
        client._emit({"i": i})
    assert client.dropped > 0
    assert client._queue.qsize() <= 3
    started.set()
    client.close(timeout_s=2.0)


# ------------------------------------------------------------------ add-agent-self-discovery: whoami()
def test_whoami_returns_the_response_json(monkeypatch):
    captured = {}

    def fake_get(url, *, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "name": "my-reasoner",
                "kind": "reasoning",
                "declared_models": {"reasoning": "qwen3:8b"},
                "gateway_model_groups": {"reasoning": "my-reasoner__reasoning"},
            },
            request=httpx.Request("GET", url),
        )

    import eval_agent_sdk

    monkeypatch.setattr(eval_agent_sdk.httpx, "get", fake_get)

    body = whoami("http://platform.local", "tok-123")
    assert body["gateway_model_groups"] == {"reasoning": "my-reasoner__reasoning"}
    assert captured["url"] == "http://platform.local/api/ingest/v1/whoami"
    assert captured["headers"] == {"Authorization": "Bearer tok-123"}
    assert captured["timeout"] == 10.0


def test_whoami_strips_a_trailing_slash_from_the_platform_url(monkeypatch):
    captured = {}

    def fake_get(url, *, headers=None, timeout=None):
        captured["url"] = url
        return httpx.Response(200, json={}, request=httpx.Request("GET", url))

    import eval_agent_sdk

    monkeypatch.setattr(eval_agent_sdk.httpx, "get", fake_get)
    whoami("http://platform.local/", "tok")
    assert captured["url"] == "http://platform.local/api/ingest/v1/whoami"


def test_whoami_raises_on_a_non_2xx_response(monkeypatch):
    def fake_get(url, *, headers=None, timeout=None):
        return httpx.Response(401, json={"detail": "unauthorized"}, request=httpx.Request("GET", url))

    import eval_agent_sdk

    monkeypatch.setattr(eval_agent_sdk.httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        whoami("http://platform.local", "bad-token")


def test_whoami_raises_on_a_connection_failure(monkeypatch):
    def fake_get(url, *, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    import eval_agent_sdk

    monkeypatch.setattr(eval_agent_sdk.httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPError):
        whoami("http://platform.local", "tok")
