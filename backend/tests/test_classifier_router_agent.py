"""`add-classifier-router-agent`: the classifier-routed multi-agent orchestrator's discovery, routing-decision,
span-recording and branching behavior, against a fake platform/gateway/classifier/MCP tool (no live process
needed - see the live verification done directly against a running platform/gateway for section 6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

import classifier_router_agent as router_agent  # noqa: E402
from eval_agent_sdk import AgentClient  # noqa: E402


def _platform_handler(received: list):
    def handler(request: httpx.Request) -> httpx.Response:
        received.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0, "rejected": []})

    return handler


# ------------------------------------------------------------------ 3.2/3.6 self-discovery
def test_discovery_is_used_when_no_override_is_given(monkeypatch):
    def fake_whoami(platform_url, token):
        assert platform_url == "http://platform.local"
        assert token == "tok"
        return {
            "gateway_model_groups": {"routing": "my-router__routing"},
            "custom_model_endpoints": {"classification": {"base_url": "http://127.0.0.1:9999", "model_id": "classify"}},
        }

    monkeypatch.setattr(router_agent, "whoami", fake_whoami)
    group, url = router_agent._resolve_routing_group_and_classifier_url("http://platform.local", "tok", None, None)
    assert group == "my-router__routing"
    assert url == "http://127.0.0.1:9999"


def test_explicit_overrides_win_without_consulting_discovery():
    def fail_whoami(*a, **kw):
        raise AssertionError("whoami() must not be called when both overrides are already explicit")

    import unittest.mock

    with unittest.mock.patch.object(router_agent, "whoami", fail_whoami):
        group, url = router_agent._resolve_routing_group_and_classifier_url(
            "http://platform.local", "tok", "explicit__routing", "http://explicit:1234"
        )
    assert (group, url) == ("explicit__routing", "http://explicit:1234")


def test_whoami_is_still_called_when_only_one_of_two_is_explicit(monkeypatch):
    calls = {"n": 0}

    def fake_whoami(platform_url, token):
        calls["n"] += 1
        return {
            "gateway_model_groups": {"routing": "discovered__routing"},
            "custom_model_endpoints": {},
        }

    monkeypatch.setattr(router_agent, "whoami", fake_whoami)
    group, url = router_agent._resolve_routing_group_and_classifier_url(
        "http://platform.local", "tok", None, "http://explicit:1234"
    )
    assert calls["n"] == 1
    assert group == "discovered__routing"
    assert url == "http://explicit:1234"  # the override, not consulted from discovery


def test_an_explicit_override_wins_for_its_own_value_even_when_the_other_is_discovered(monkeypatch):
    def fake_whoami(platform_url, token):
        return {
            "gateway_model_groups": {"routing": "discovered__routing"},
            "custom_model_endpoints": {"classification": {"base_url": "http://discovered:1", "model_id": "m"}},
        }

    monkeypatch.setattr(router_agent, "whoami", fake_whoami)
    group, url = router_agent._resolve_routing_group_and_classifier_url(
        "http://platform.local", "tok", "explicit__routing", None
    )
    assert group == "explicit__routing"
    assert url == "http://discovered:1"


def test_failed_discovery_falls_back_to_hardcoded_defaults_with_a_visible_warning(monkeypatch, capsys):
    def fake_whoami(platform_url, token):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", platform_url))

    monkeypatch.setattr(router_agent, "whoami", fake_whoami)
    group, url = router_agent._resolve_routing_group_and_classifier_url("http://platform.local", "tok", None, None)
    assert group == router_agent.ROUTING_MODEL_GROUP
    assert url == router_agent.DEFAULT_CLASSIFIER_URL
    assert "warning" in capsys.readouterr().err.lower()


def test_custom_model_endpoints_absent_for_classification_falls_back_to_default(monkeypatch):
    """A declared `classification` task that isn't registered at all (or doesn't resolve to a custom-kind
    provider) still starts the agent, using the hardcoded default - no warning needed, this isn't a failure,
    just nothing to discover."""

    def fake_whoami(platform_url, token):
        return {"gateway_model_groups": {"routing": "my-router__routing"}, "custom_model_endpoints": {}}

    monkeypatch.setattr(router_agent, "whoami", fake_whoami)
    _, url = router_agent._resolve_routing_group_and_classifier_url("http://platform.local", "tok", None, None)
    assert url == router_agent.DEFAULT_CLASSIFIER_URL


# ------------------------------------------------------------------ fakes for the routing decision / graph
class _FakeAIResponse:
    def __init__(self, tool_calls, model_name="ollama_chat/qwen3:8b", prompt_tokens=10, completion_tokens=5):
        self.tool_calls = tool_calls
        self.response_metadata = {
            "headers": {"x-litellm-model-name": model_name},
            "token_usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }

    content = ""


class _FakeBoundLLM:
    def __init__(self, response):
        self._response = response
        self.invoked_with = None

    def invoke(self, messages):
        self.invoked_with = messages
        return self._response


class _FakeLLM:
    """Stands in for `ChatOpenAI` - `routing_decision()` only ever calls `.bind_tools([...]).invoke(...)` and
    reads `.model_name`."""

    model_name = "classifier-router-agent__routing"

    def __init__(self, response):
        self._response = response
        self.bound_tools = None
        self.bound = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        self.bound = _FakeBoundLLM(self._response)
        return self.bound


# ------------------------------------------------------------------ 4.1/4.2 routing_decision
def test_routing_decision_calls_the_tool_and_uses_its_result_directly():
    calls = []

    def fake_call_tool(classification):
        calls.append(classification)
        return {"action": "short_circuit", "response": "spam, ignored"}

    response = _FakeAIResponse(
        [{"name": "resolve_route", "args": {"classification": {"spam": {"label": "spam"}}}, "id": "1"}]
    )
    llm = _FakeLLM(response)
    decision, model, usage = router_agent.routing_decision(llm, {"spam": {"label": "spam"}}, call_tool=fake_call_tool)
    assert decision == {"action": "short_circuit", "response": "spam, ignored"}
    assert model == "ollama_chat/qwen3:8b"
    assert usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert calls == [{"spam": {"label": "spam"}}]


def test_routing_decision_executes_only_the_first_tool_call_even_if_more_are_requested():
    calls = []

    def fake_call_tool(classification):
        calls.append(classification)
        return {"action": "error"}

    response = _FakeAIResponse(
        [
            {"name": "resolve_route", "args": {"classification": {"a": 1}}, "id": "1"},
            {"name": "resolve_route", "args": {"classification": {"b": 2}}, "id": "2"},
        ]
    )
    llm = _FakeLLM(response)
    router_agent.routing_decision(llm, {"x": 1}, call_tool=fake_call_tool)
    assert len(calls) == 1
    assert calls[0] == {"a": 1}  # only the first requested call was ever executed


def test_routing_decision_raises_when_the_model_never_calls_the_tool():
    response = _FakeAIResponse([])
    llm = _FakeLLM(response)
    with pytest.raises(router_agent.RoutingToolNotCalled):
        router_agent.routing_decision(llm, {"x": 1}, call_tool=lambda c: {"action": "error"})


# ------------------------------------------------------------------ 4.3/4.4/5.1/5.2/5.3 the graph / full turn
def _patched_agent(monkeypatch, *, classification, tool_result, reasoning_output=None, handoff_error=None):
    """Wires `classifier_router_agent` so a turn runs end to end against fakes only: `classify()` returns
    `classification`, the routing LLM always calls the tool, `call_resolve_route()` returns `tool_result`
    without touching any real MCP subprocess, and (for a handoff) `spawn_reasoning_agent()` returns
    `reasoning_output` or raises `handoff_error`, without spawning a real subprocess."""
    monkeypatch.setattr(router_agent, "classify", lambda url, problem, **kw: classification)
    monkeypatch.setattr(router_agent, "call_resolve_route", lambda c: tool_result)

    def fake_make_routing_llm(gateway_url, gateway_key, model, *, fallback_group=None, timeout=60.0):
        response = _FakeAIResponse([{"name": "resolve_route", "args": {"classification": classification}, "id": "1"}])
        return _FakeLLM(response)

    monkeypatch.setattr(router_agent, "make_routing_llm", fake_make_routing_llm)

    def fake_spawn(problem, **kw):
        if handoff_error is not None:
            raise handoff_error
        return reasoning_output

    monkeypatch.setattr(router_agent, "spawn_reasoning_agent", fake_spawn)


def _run_turn(monkeypatch, *, tracer_provider=None, **patch_kwargs):
    _patched_agent(monkeypatch, **patch_kwargs)
    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        tracer_provider=tracer_provider,
        flush_interval_s=0.02,
    )
    final = router_agent.solve_one(
        client,
        "s1",
        "http://gateway.local",
        "gw-key",
        "Apple stock surged today.",
        classifier_url="http://classifier.local",
        platform_url="http://platform.local",
        reasoning_agent_token="ra-token",
        reasoning_agent_gateway_key="ra-gw-key",
    )
    client.close(timeout_s=2.0)
    return final, received


def test_handoff_turn_has_classify_routing_llm_and_handoff_tool_spans_in_order(monkeypatch):
    """add-otel-tracing: the three calls are now three real OTel spans, not JSON "span" events -
    the classify/handoff tool spans use GenAI semconv's own tool-call attributes (classify's `model`
    names the external classifier endpoint, not a generative model - still the same
    `gen_ai.request.model` key as the routing call's own model, so one query finds either), the
    routing call also carries `eval.kind` (its role in the turn) alongside its GenAI attributes."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))

    final, received = _run_turn(
        monkeypatch,
        tracer_provider=provider,
        classification={"ag_news": {"label": "Business"}},
        tool_result={"action": "handoff", "target_agent": "reasoning-agent"},
        reasoning_output="**Final answer:** <answer>5</answer>",
    )
    provider.shutdown()
    assert final == "**Final answer:** <answer>5</answer>"

    spans = [s for s in exp.get_finished_spans() if s.name != "agent.turn"]
    spans.sort(key=lambda s: s.start_time)
    assert [s.name for s in spans] == ["classify", "gen_ai.chat", "handoff_to_reasoning_agent"]
    assert spans[0].attributes["gen_ai.request.model"] == "http://classifier.local"  # the classifier endpoint
    assert spans[1].attributes["gen_ai.request.model"] == "ollama_chat/qwen3:8b"  # the routing span's concrete model
    assert spans[1].attributes["eval.kind"] == "routing"
    assert spans[0].attributes["gen_ai.tool.name"] == "classify"
    assert spans[2].attributes["gen_ai.tool.call.result"] == "**Final answer:** <answer>5</answer>"

    end = next(e for e in received if e["type"] == "turn.end")
    assert end["models"] == ["ollama_chat/qwen3:8b"]  # only the routing call is an llm call
    assert end["trace_id"] == format(spans[0].context.trace_id, "032x")  # all under one trace


def test_short_circuit_turn_has_no_further_spans_after_the_routing_decision(monkeypatch):
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))

    final, received = _run_turn(
        monkeypatch,
        tracer_provider=provider,
        classification={"spam": {"label": "spam"}},
        tool_result={"action": "short_circuit", "response": "This looks like spam."},
    )
    provider.shutdown()
    assert final == "This looks like spam."

    spans = [s for s in exp.get_finished_spans() if s.name != "agent.turn"]
    spans.sort(key=lambda s: s.start_time)
    assert [s.name for s in spans] == ["classify", "gen_ai.chat", "short_circuit"]
    assert spans[2].attributes["gen_ai.tool.call.result"] == "This looks like spam."
    # never spawned the reasoning-agent subprocess or made a second LLM call for this branch
    assert len([s for s in spans if s.name == "gen_ai.chat"]) == 1


def test_an_unmapped_result_ends_the_turn_in_a_visible_error_not_a_guess(monkeypatch):
    with pytest.raises(router_agent.NoRouteMatched):
        _run_turn(
            monkeypatch,
            classification={"some_other_task": {"label": "whatever"}},
            tool_result={"action": "error"},
        )


def test_a_failed_handoff_records_the_tool_span_as_an_error_and_fails_the_turn(monkeypatch):
    with pytest.raises(RuntimeError, match="reasoning_agent exited"):
        _run_turn(
            monkeypatch,
            classification={"ag_news": {"label": "Business"}},
            tool_result={"action": "handoff", "target_agent": "reasoning-agent"},
            handoff_error=RuntimeError("reasoning_agent exited with 1: boom"),
        )


def test_the_graph_branches_only_on_the_tools_action_not_on_the_classification_content(monkeypatch):
    """4.4: the exact same classification result, with only the tool's returned action varied, takes a
    different branch - proving the branch is driven by the tool's action, never by the orchestrator's own
    code inspecting the classifier's raw labels."""
    same_classification = {"ag_news": {"label": "Business"}, "spam": {"label": "ham"}}

    final_handoff, received_handoff = _run_turn(
        monkeypatch,
        classification=same_classification,
        tool_result={"action": "handoff", "target_agent": "reasoning-agent"},
        reasoning_output="handoff answer",
    )
    assert final_handoff == "handoff answer"

    final_short, received_short = _run_turn(
        monkeypatch,
        classification=same_classification,
        tool_result={"action": "short_circuit", "response": "short-circuit answer"},
    )
    assert final_short == "short-circuit answer"


# ------------------------------------------------------------------ add-otel-tracing: --otel-endpoint
def test_otel_endpoint_falls_back_to_the_env_var_when_the_flag_is_omitted(monkeypatch):
    monkeypatch.setenv("EVAL_OTEL_ENDPOINT", "localhost:4317")
    args = router_agent.build_arg_parser().parse_args(
        [
            "--platform-url", "http://platform.local", "--token", "tok", "--gateway-key", "gw-key",
            "--reasoning-agent-token", "ra-token", "--reasoning-agent-gateway-key", "ra-gw-key",
            "--problem", "x",
        ]
    )
    assert args.otel_endpoint == "localhost:4317"


def test_otel_endpoint_defaults_to_none_when_the_env_var_is_unset(monkeypatch):
    monkeypatch.delenv("EVAL_OTEL_ENDPOINT", raising=False)
    args = router_agent.build_arg_parser().parse_args(
        [
            "--platform-url", "http://platform.local", "--token", "tok", "--gateway-key", "gw-key",
            "--reasoning-agent-token", "ra-token", "--reasoning-agent-gateway-key", "ra-gw-key",
            "--problem", "x",
        ]
    )
    assert args.otel_endpoint is None


def test_main_wires_a_fixed_workflow_name_into_the_agent_client(monkeypatch):
    """add-otel-tracing: this agent's turn is a real LangGraph `StateGraph`, unlike chatbot.py's
    single call - `main()` always passes a literal `workflow_name` for it."""
    _patched_agent(
        monkeypatch,
        classification={"spam": {"label": "spam"}},
        tool_result={"action": "short_circuit", "response": "short-circuit answer"},
    )
    captured = {}

    def fake_agent_client(*_a, **kw):
        captured.update(kw)
        return AgentClient(
            "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler([])),
            flush_interval_s=0.02,
        )

    monkeypatch.setattr(router_agent, "AgentClient", fake_agent_client)
    router_agent.main([
        "--platform-url", "http://platform.local", "--token", "tok", "--gateway-key", "gw-key",
        "--routing-model-group", "explicit__routing", "--classifier-url", "http://classifier.local",
        "--reasoning-agent-token", "ra-token", "--reasoning-agent-gateway-key", "ra-gw-key",
        "--problem", "Apple stock surged today.",
    ])
    assert captured["workflow_name"] == "classifier-router-graph"
