"""Tests for the standalone agent SDK (agents/eval_agent_sdk). Imported via a sys.path insert rather than a
package install, since it is a separate, dependency-light package meant to run inside a *deployed agent's*
process, not inside the platform backend."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

from eval_agent_sdk import AgentClient  # noqa: E402


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
        t.llm_call(model="qwen3:8b", output="hi there")
        t.finish("hi there")
    client.close(timeout_s=2.0)

    types = [e["type"] for e in received]
    assert "turn.start" in types
    assert "span" in types
    assert "turn.end" in types
    end = next(e for e in received if e["type"] == "turn.end")
    assert end["status"] == "ok"
    assert end["output"] == "hi there"


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
