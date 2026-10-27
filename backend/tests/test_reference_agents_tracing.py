"""add-otel-tracing 7.1/7.2/7.3: each reference agent's calls produce real OpenTelemetry spans when
tracing is configured, with no change to its own call sites beyond wiring `otel_endpoint` through."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

import chatbot  # noqa: E402
from eval_agent_sdk import AgentClient  # noqa: E402


class _FakeOllamaResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self._content}, "prompt_eval_count": 10, "eval_count": 5}


def _platform_handler(received: list):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": len(received), "duplicates": 0, "rejected": []})

    return handler


def test_chatbots_call_produces_a_real_span_in_one_trace_matching_turn_end(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeOllamaResponse("Hello there!")

    monkeypatch.setattr(chatbot.httpx, "post", fake_post)

    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        tracer_provider=provider,
        flush_interval_s=0.02,
    )
    chatbot.answer(client, "s1", "qwen3:8b", "http://ollama.local", chatbot.DEFAULT_SYSTEM_PROMPT, [], "hi")
    client.close(timeout_s=2.0)
    provider.shutdown()

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert call_span.attributes["gen_ai.request.model"] == "qwen3:8b"
    assert call_span.attributes["gen_ai.usage.input_tokens"] == 10
    assert call_span.attributes["gen_ai.usage.output_tokens"] == 5

    end = next(e for e in received if e["type"] == "turn.end")
    assert end["trace_id"] == format(call_span.context.trace_id, "032x")
