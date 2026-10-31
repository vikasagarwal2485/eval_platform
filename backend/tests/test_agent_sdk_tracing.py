"""add-otel-tracing 6.1/6.2/6.3/6.5: the agent SDK's real OpenTelemetry instrumentation.

Imported the same way as test_agent_sdk.py (a separate, dependency-light-no-more package, not an
installed one)."""

from __future__ import annotations

import sys
from concurrent import futures
from pathlib import Path

import grpc
import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import (
    TraceServiceServicer,
    add_TraceServiceServicer_to_server,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

from eval_agent_sdk import AgentClient  # noqa: E402
from eval_agent_sdk.tracing import compute_cost, setup_tracing  # noqa: E402


class _FakeOtlpReceiver(TraceServiceServicer):
    """A real (minimal) OTLP/gRPC trace receiver - decodes the actual wire protocol `setup_tracing()`'s
    `OTLPSpanExporter` sends, unlike the InMemorySpanExporter-based tests below (which bypass OTLP
    entirely to test the SDK's own span-attribute-setting logic in isolation)."""

    def __init__(self):
        self.requests = []

    def Export(self, request, context):
        self.requests.append(request)
        return ExportTraceServiceResponse()

    def span_names(self) -> list[str]:
        return [
            span.name
            for req in self.requests
            for rs in req.resource_spans
            for ss in rs.scope_spans
            for span in ss.spans
        ]


@pytest.fixture
def fake_otlp_receiver():
    receiver = _FakeOtlpReceiver()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    add_TraceServiceServicer_to_server(receiver, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield receiver, f"127.0.0.1:{port}"
    server.stop(grace=None)


@pytest.fixture
def exporter():
    """An in-memory exporter, synchronous (SimpleSpanProcessor - no batching delay)."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    yield exp, provider
    provider.shutdown()


def _client(provider, handler=None):
    def default_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"accepted": 0, "duplicates": 0, "rejected": []})

    transport = httpx.MockTransport(handler or default_handler)
    return AgentClient(
        "http://platform.local", "tok", transport=transport, tracer_provider=provider, flush_interval_s=0.05
    )


# ------------------------------------------------------------------ 6.1: tracer setup
def test_setup_tracing_is_a_no_op_when_endpoint_is_unset():
    assert setup_tracing(None) is None


def test_setup_tracing_against_an_unreachable_endpoint_still_constructs_a_provider():
    """Construction never contacts the endpoint - exporting does, and that's the SDK's own
    BatchSpanProcessor's problem, not this function's."""
    provider = setup_tracing("http://127.0.0.1:1", service_name="test-agent")
    assert provider is not None
    provider.shutdown()


def test_configuring_against_a_fake_otlp_receiver_produces_spans_with_the_expected_shape(fake_otlp_receiver):
    """6.1's own verification: a real span, sent over the real OTLP/gRPC wire protocol (not bypassed
    via an in-memory exporter), actually arrives at a receiver and decodes with the expected shape."""
    receiver, endpoint = fake_otlp_receiver
    provider = setup_tracing(endpoint, service_name="test-agent")
    assert provider is not None
    try:
        with provider.get_tracer("test").start_as_current_span("gen_ai.chat") as span:
            span.set_attribute("gen_ai.request.model", "qwen3:8b")
    finally:
        provider.shutdown()  # flushes the BatchSpanProcessor before the assertion below

    assert receiver.span_names() == ["gen_ai.chat"]


# ------------------------------------------------------------------ 6.2: llm_call spans
def test_llm_call_emits_a_span_with_genai_attributes_and_cost(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="gpt-4o", output="hello", prompt_tokens=1000, completion_tokens=1000, ttft_ms=120.0)
        t.finish("hello")
    client.close(timeout_s=2.0)

    spans = exp.get_finished_spans()
    (call_span,) = [s for s in spans if s.name == "gen_ai.chat"]
    assert call_span.attributes["gen_ai.operation.name"] == "chat"
    assert call_span.attributes["gen_ai.request.model"] == "gpt-4o"
    assert call_span.attributes["gen_ai.usage.input_tokens"] == 1000
    assert call_span.attributes["gen_ai.usage.output_tokens"] == 1000
    assert call_span.attributes["eval.cost"] == pytest.approx(0.0025 + 0.01)  # app/data/model_pricing.yaml's gpt-4o
    assert call_span.attributes["eval.ttft_ms"] == 120.0
    assert call_span.status.status_code == StatusCode.OK


def test_llm_call_kind_names_the_calls_role_when_a_turn_makes_more_than_one(exporter):
    """Every llm_call shares the same span name ("gen_ai.chat") *and* the same
    `gen_ai.operation.name` ("chat" - GenAI semconv's own enum has nothing finer) - without `kind`,
    two calls in the same turn (e.g. reasoning_agent's classify/plan/solve/verify) would be
    indistinguishable even with both of those."""
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", output="a", kind="plan")
        t.llm_call(model="qwen3:8b", output="b", kind="solve")
        t.finish("b")
    client.close(timeout_s=2.0)

    spans = sorted((s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"), key=lambda s: s.start_time)
    assert [s.attributes["eval.kind"] for s in spans] == ["plan", "solve"]
    assert [s.attributes["gen_ai.operation.name"] for s in spans] == ["chat", "chat"]  # identical either way


def test_llm_call_kind_is_omitted_not_fabricated_when_not_given(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", output="a")
        t.finish("a")
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert "eval.kind" not in call_span.attributes


def test_llm_call_apportions_reasoning_tokens_from_thinking_text_share(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        # 20 "thinking" chars, 10 "output" chars -> thinking is 2/3 of the combined text
        t.llm_call(
            model="qwen3:8b", output="a" * 10, thinking="b" * 20, completion_tokens=300, kind="plan",
        )
        t.finish("a" * 10)
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert call_span.attributes["gen_ai.usage.reasoning.output_tokens"] == 200  # round(300 * 20/30)
    assert call_span.attributes["eval.reasoning_tokens_approx"] is True


def test_llm_call_omits_reasoning_tokens_without_thinking_text(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", output="a", completion_tokens=300)
        t.finish("a")
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert "gen_ai.usage.reasoning.output_tokens" not in call_span.attributes
    assert "eval.reasoning_tokens_approx" not in call_span.attributes


def test_llm_call_omits_reasoning_tokens_without_a_completion_token_count(exporter):
    """Never fabricated: thinking text alone, with nothing to apportion it against, stays absent."""
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", output="a", thinking="deliberating...")
        t.finish("a")
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert "gen_ai.usage.reasoning.output_tokens" not in call_span.attributes


def test_llm_call_with_an_error_sets_span_status_to_error(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", error="timed out")
        t.finish("")
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert call_span.status.status_code == StatusCode.ERROR


def test_an_unpriced_model_gets_no_cost_attribute_at_all(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", prompt_tokens=10, completion_tokens=5)
        t.finish("")
    client.close(timeout_s=2.0)

    (call_span,) = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert "eval.cost" not in call_span.attributes  # never fabricated as 0


# ------------------------------------------------------------------ 6.3: tool_call spans
def test_tool_call_emits_a_span_with_genai_tool_attributes(exporter):
    """GenAI semconv's own tool-call attributes (unlike `eval.kind`, the spec genuinely defines
    these), not this SDK's earlier ad hoc `tool.*` names."""
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.tool_call(
            name="lookup_weather", args={"city": "Paris"}, result="sunny",
            description="Looks up current weather", call_id="call-1",
        )
        t.finish("It's sunny in Paris")
    client.close(timeout_s=2.0)

    (tool_span,) = [s for s in exp.get_finished_spans() if s.name == "lookup_weather"]
    assert tool_span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool_span.attributes["gen_ai.tool.name"] == "lookup_weather"
    assert tool_span.attributes["gen_ai.tool.type"] == "function"  # the default
    assert tool_span.attributes["gen_ai.tool.description"] == "Looks up current weather"
    assert tool_span.attributes["gen_ai.tool.call.id"] == "call-1"
    assert "Paris" in tool_span.attributes["gen_ai.tool.call.arguments"]
    assert tool_span.attributes["gen_ai.tool.call.result"] == "sunny"
    assert tool_span.status.status_code == StatusCode.OK
    assert "gen_ai.request.model" not in tool_span.attributes  # omitted here - this call didn't name one


def test_tool_call_description_and_call_id_are_omitted_not_fabricated_when_not_given(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.tool_call(name="lookup_weather", result="sunny")
        t.finish("sunny")
    client.close(timeout_s=2.0)

    (tool_span,) = [s for s in exp.get_finished_spans() if s.name == "lookup_weather"]
    assert "gen_ai.tool.description" not in tool_span.attributes
    assert "gen_ai.tool.call.id" not in tool_span.attributes


def test_tool_call_can_name_the_model_or_service_that_answered_it(exporter):
    """Some "tools" are themselves backed by a specific model/service (e.g. an external classifier) -
    naming it uses the same `gen_ai.request.model` key `llm_call()` uses, not a separate one, so one
    query finds every span about that model regardless of which method emitted it."""
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.tool_call(name="classify", result="spam", model="http://classifier.local")
        t.finish("spam")
    client.close(timeout_s=2.0)

    (tool_span,) = [s for s in exp.get_finished_spans() if s.name == "classify"]
    assert tool_span.attributes["gen_ai.request.model"] == "http://classifier.local"


def test_tool_call_with_an_error_sets_span_status_to_error(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.tool_call(name="lookup_weather", error="service unavailable")
        t.finish("")
    client.close(timeout_s=2.0)

    (tool_span,) = [s for s in exp.get_finished_spans() if s.name == "lookup_weather"]
    assert tool_span.status.status_code == StatusCode.ERROR
    assert tool_span.attributes["eval.error"] == "service unavailable"


def test_a_no_op_client_without_tracing_configured_sends_no_spans_at_all():
    """`AgentClient` built with no `tracer_provider`/`otel_endpoint` - the fully graceful case."""
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(lambda r: httpx.Response(202, json={})),
        flush_interval_s=0.05,
    )
    with client.turn("s1", input="hi") as t:
        t.llm_call(model="qwen3:8b", output="hello")
        t.tool_call(name="noop")
        t.finish("hello")
    assert t.trace_id is None
    client.close(timeout_s=2.0)


def test_agent_identity_is_set_on_the_turns_own_root_span_when_given(exporter):
    """GenAI semconv's agent-identity attributes - set once per turn from whatever the client was
    given at construction, never fabricated."""
    exp, provider = exporter
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(lambda r: httpx.Response(202, json={"accepted": 0, "duplicates": 0, "rejected": []})),
        tracer_provider=provider,
        flush_interval_s=0.05,
        agent_name="reasoning-agent",
        agent_id="42",
        agent_description="Reference multi-step reasoning agent",
    )
    with client.turn("s1", input="hi") as t:
        t.finish("hello")
    client.close(timeout_s=2.0)

    (root,) = [s for s in exp.get_finished_spans() if s.name == "agent.turn"]
    assert root.attributes["gen_ai.agent.name"] == "reasoning-agent"
    assert root.attributes["gen_ai.agent.id"] == "42"
    assert root.attributes["gen_ai.agent.description"] == "Reference multi-step reasoning agent"


def test_agent_identity_is_omitted_not_fabricated_when_not_given(exporter):
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.finish("hello")
    client.close(timeout_s=2.0)

    (root,) = [s for s in exp.get_finished_spans() if s.name == "agent.turn"]
    assert "gen_ai.agent.name" not in root.attributes
    assert "gen_ai.agent.id" not in root.attributes
    assert "gen_ai.agent.description" not in root.attributes


def test_workflow_name_is_set_on_the_turns_root_span_with_invoke_workflow_operation(exporter):
    """`gen_ai.workflow.name` + `gen_ai.operation.name="invoke_workflow"` - only when the client
    was actually given a workflow name (e.g. reasoning_agent.py's fixed pipeline)."""
    exp, provider = exporter
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(lambda r: httpx.Response(202, json={"accepted": 0, "duplicates": 0, "rejected": []})),
        tracer_provider=provider,
        flush_interval_s=0.05,
        workflow_name="reasoning-pipeline",
    )
    with client.turn("s1", input="hi") as t:
        t.finish("hello")
    client.close(timeout_s=2.0)

    (root,) = [s for s in exp.get_finished_spans() if s.name == "agent.turn"]
    assert root.attributes["gen_ai.workflow.name"] == "reasoning-pipeline"
    assert root.attributes["gen_ai.operation.name"] == "invoke_workflow"


def test_workflow_name_is_omitted_not_fabricated_when_not_given(exporter):
    """e.g. chatbot.py's turn is a single call, not a workflow - it never passes `workflow_name`."""
    exp, provider = exporter
    client = _client(provider)
    with client.turn("s1", input="hi") as t:
        t.finish("hello")
    client.close(timeout_s=2.0)

    (root,) = [s for s in exp.get_finished_spans() if s.name == "agent.turn"]
    assert "gen_ai.workflow.name" not in root.attributes
    assert "gen_ai.operation.name" not in root.attributes


# ------------------------------------------------------------------ 6.5: one trace, ordered spans
def test_multiple_calls_in_one_turn_share_one_trace_with_spans_in_order(exporter):
    exp, provider = exporter
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": len(received), "duplicates": 0, "rejected": []})

    client = _client(provider, handler)
    with client.turn("s1", input="plan a trip") as t:
        t.llm_call(model="gpt-4o-mini", output="step 1", prompt_tokens=10, completion_tokens=5)
        t.tool_call(name="search_flights", result="found 3 options")
        t.llm_call(model="gpt-4o-mini", output="step 2", prompt_tokens=20, completion_tokens=8)
        t.finish("done")
    client.close(timeout_s=2.0)

    spans = exp.get_finished_spans()
    names_in_order = [s.name for s in sorted(spans, key=lambda s: s.start_time)]
    assert names_in_order == ["agent.turn", "gen_ai.chat", "search_flights", "gen_ai.chat"]

    trace_ids = {format(s.context.trace_id, "032x") for s in spans}
    assert len(trace_ids) == 1  # one trace for the whole turn
    (reported_trace_id,) = trace_ids

    end = next(e for e in received if e["type"] == "turn.end")
    assert end["trace_id"] == reported_trace_id
    assert end["models"] == ["gpt-4o-mini"]  # de-duplicated
    assert end["prompt_tokens"] == 30 and end["completion_tokens"] == 13  # summed across both calls
    assert end["cost"] == pytest.approx(compute_cost("gpt-4o-mini", 10, 5) + compute_cost("gpt-4o-mini", 20, 8))

    # every call span (not the root) is a child of the turn's own root span
    root = next(s for s in spans if s.name == "agent.turn")
    for s in spans:
        if s is not root:
            assert s.parent.span_id == root.context.span_id
