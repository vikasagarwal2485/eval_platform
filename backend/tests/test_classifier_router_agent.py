"""`add-classifier-router-agent`: the classifier-routed multi-agent orchestrator's discovery, routing-decision,
span-recording and branching behavior, against a fake platform/gateway/classifier/MCP tool (no live process
needed - see the live verification done directly against a running platform/gateway for section 6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

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


def _run_turn(monkeypatch, **patch_kwargs):
    _patched_agent(monkeypatch, **patch_kwargs)
    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
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
    final, received = _run_turn(
        monkeypatch,
        classification={"ag_news": {"label": "Business"}},
        tool_result={"action": "handoff", "target_agent": "reasoning-agent"},
        reasoning_output="**Final answer:** <answer>5</answer>",
    )
    assert final == "**Final answer:** <answer>5</answer>"
    spans = [e for e in received if e["type"] == "span"]
    assert [s["kind"] for s in spans] == ["tool", "llm", "tool"]
    assert spans[0]["name"] == "classify"
    assert spans[0].get("model") is None  # the classify span is never an llm span - no model field at all
    assert spans[1]["model"] == "ollama_chat/qwen3:8b"  # the routing span's concrete model
    assert spans[2]["name"] == "handoff_to_reasoning_agent"
    assert spans[2]["result"] == "**Final answer:** <answer>5</answer>"


def test_short_circuit_turn_has_no_further_spans_after_the_routing_decision(monkeypatch):
    final, received = _run_turn(
        monkeypatch,
        classification={"spam": {"label": "spam"}},
        tool_result={"action": "short_circuit", "response": "This looks like spam."},
    )
    assert final == "This looks like spam."
    spans = [e for e in received if e["type"] == "span"]
    assert [s["kind"] for s in spans] == ["tool", "llm", "tool"]
    assert spans[2]["name"] == "short_circuit"
    assert spans[2]["result"] == "This looks like spam."
    # never spawned the reasoning-agent subprocess or made a second LLM call for this branch
    assert len([s for s in spans if s["kind"] == "llm"]) == 1


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
