"""Scripted runs of the reference agents against a fake Ollama/gateway and a fake platform (task 7.1/7.2,
`add-reasoning-agent-task-routing`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import openai

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

import chatbot  # noqa: E402
import reasoning_agent  # noqa: E402
from eval_agent_sdk import AgentClient  # noqa: E402


class _FakeOllamaResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self._content}, "prompt_eval_count": 10, "eval_count": 5}


class _FailingOllamaResponse:
    """Simulates a 404 (e.g. --model not pulled): raise_for_status() raises, as httpx does for real."""

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            "404 Not Found", request=httpx.Request("POST", "http://x"), response=httpx.Response(404)
        )


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeLiteLLMResponse:
    """Shaped like a real `litellm.completion()` return value (verified directly against a running gateway
    while implementing add-litellm-gateway-infra): `.model` is the group alias the caller addressed, and the
    *concrete* deployment that actually answered is only in `_hidden_params`, under the proxied
    `x-litellm-model-name` header."""

    def __init__(self, content: str, *, concrete_model: str | None = None):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]
        self.usage = _FakeUsage(10, 5)
        self._hidden_params = (
            {"additional_headers": {"llm_provider-x-litellm-model-name": concrete_model}} if concrete_model else {}
        )


def _platform_handler(received: list):
    def handler(request: httpx.Request) -> httpx.Response:
        received.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0, "rejected": []})

    return handler


def test_chatbot_one_exchange_produces_one_turn_one_span(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeOllamaResponse("Hello there!")

    monkeypatch.setattr(chatbot.httpx, "post", fake_post)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    chatbot.answer(client, "s1", "qwen3:8b", "http://ollama.local", chatbot.DEFAULT_SYSTEM_PROMPT, [], "hi")
    client.close(timeout_s=2.0)

    types = [e["type"] for e in received]
    assert types.count("turn.start") == 1
    assert types.count("span") == 1
    assert types.count("turn.end") == 1
    end = next(e for e in received if e["type"] == "turn.end")
    assert end["output"] == "Hello there!"


def test_reasoning_agent_one_problem_produces_three_spans_under_one_turn(monkeypatch):
    answers = iter(["1. Do X", "Working: ...", "Final answer: 42"])

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse(next(answers))

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    final = reasoning_agent.solve_one(
        client, "s1", "ollama_chat/qwen3:8b", "http://gateway.local", None, "2+3?", reference="5"
    )
    client.close(timeout_s=2.0)

    assert "42" in final
    turn_id = {e["turn_id"] for e in received}
    assert len(turn_id) == 1  # every event belongs to the same turn
    spans = [e for e in received if e["type"] == "span"]
    assert len(spans) == 3
    start = next(e for e in received if e["type"] == "turn.start")
    assert start["reference"] == "5"


def test_reasoning_agent_default_mode_routes_plan_verify_and_solve_to_different_task_model_groups(monkeypatch):
    """`model=None` (the CLI default) - plan/verify address `REASONING_MODEL_GROUP`, solve addresses
    `GENERATION_MODEL_GROUP`, each prefixed `openai/` and sent through the gateway's `api_base` (the SDK needs
    that prefix to treat an arbitrary `api_base` as an OpenAI-compatible endpoint - verified directly against a
    running gateway while implementing add-litellm-gateway-infra; a bare group name fails there)."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", "vkey-123", "2+3?")
    client.close(timeout_s=2.0)

    assert [c["model"] for c in calls] == [
        f"openai/{reasoning_agent.REASONING_MODEL_GROUP}",
        f"openai/{reasoning_agent.GENERATION_MODEL_GROUP}",
        f"openai/{reasoning_agent.REASONING_MODEL_GROUP}",
    ]
    assert all(c["api_base"] == "http://gateway.local" for c in calls)
    assert all(c["api_key"] == "vkey-123" for c in calls)


def test_reasoning_and_generation_model_groups_are_overridable(monkeypatch):
    """TEMPORARY stopgap (see the module docstring and add-gateway-model-sync's design.md Non-Goals):
    --reasoning-model-group/--generation-model-group let an operator point at an agent registered under any
    name, not just the hardcoded "reasoning-agent" default."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(
        client, "s1", None, "http://gateway.local", "vkey-123", "2+3?",
        reasoning_group="my-reasoner__reasoning", generation_group="my-reasoner__generation",
    )
    client.close(timeout_s=2.0)

    assert [c["model"] for c in calls] == [
        "openai/my-reasoner__reasoning",
        "openai/my-reasoner__generation",
        "openai/my-reasoner__reasoning",
    ]


def test_cli_overrides_thread_through_run_once(monkeypatch):
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.run_once(
        client, None, "http://gateway.local", "vkey-123", "2+3?",
        reasoning_group="demo__reasoning", generation_group="demo__generation",
    )
    client.close(timeout_s=2.0)

    assert calls[0]["model"] == "openai/demo__reasoning"
    assert calls[1]["model"] == "openai/demo__generation"


def test_reasoning_agent_explicit_model_skips_the_gateway_for_all_three_calls(monkeypatch):
    """`--model` overrides all three calls to one literal model string with no gateway involved - local testing
    without the gateway running at all."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", "ollama_chat/qwen3:8b", "http://gateway.local", "vkey-123", "2+3?")
    client.close(timeout_s=2.0)

    assert [c["model"] for c in calls] == ["ollama_chat/qwen3:8b"] * 3
    assert all("api_base" not in c for c in calls)
    assert all("api_key" not in c for c in calls)


def test_reasoning_agent_span_records_the_concrete_model_not_the_group_alias(monkeypatch):
    """A span's `model` must be the real deployment that answered (`ollama_chat/qwen3:8b`), never the gateway's
    routing alias (`reasoning-agent__reasoning`) - `plan_turn_evaluators`/`same_model`/`same_family` key off
    this for the never-self-judge invariant, and an alias would break that check silently."""

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse("...", concrete_model="ollama_chat/qwen3:8b")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?")
    client.close(timeout_s=2.0)

    spans = [e for e in received if e["type"] == "span"]
    assert len(spans) == 3
    assert all(s["model"] == "ollama_chat/qwen3:8b" for s in spans)
    assert reasoning_agent.REASONING_MODEL_GROUP not in {s["model"] for s in spans}
    assert reasoning_agent.GENERATION_MODEL_GROUP not in {s["model"] for s in spans}


def test_call_llm_return_shape_matches_the_pre_litellm_implementation(monkeypatch):
    """task 2.1: call_llm() keeps call_ollama()'s `(content, usage)` return shape - usage is a dict carrying
    latency_ms/prompt_tokens/completion_tokens (now plus `model`, read by `_span`)."""

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse("hello", concrete_model="ollama_chat/qwen3:8b")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    content, usage = reasoning_agent.call_llm("http://gateway.local", None, "reasoning-agent__reasoning", "hi")
    assert content == "hello"
    assert isinstance(usage, dict)
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["model"] == "ollama_chat/qwen3:8b"
    assert isinstance(usage["latency_ms"], float)


def test_chatbot_repl_survives_a_failed_call_and_keeps_taking_input(monkeypatch, capsys):
    """A single failed Ollama call (wrong --model, Ollama down mid-chat, ...) must not crash the whole agent."""
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FailingOllamaResponse() if calls["n"] == 1 else _FakeOllamaResponse("Hello there!")

    monkeypatch.setattr(chatbot.httpx, "post", fake_post)
    inputs = iter(["first message", "second message", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    chatbot.run_repl(client, "qwen3:8b", "http://ollama.local", chatbot.DEFAULT_SYSTEM_PROMPT)  # must not raise
    client.close(timeout_s=2.0)

    assert calls["n"] == 2  # the REPL kept going and made the second call
    ends = [e for e in received if e["type"] == "turn.end"]
    assert len(ends) == 2
    assert {e["status"] for e in ends} == {"error", "ok"}
    ok_end = next(e for e in ends if e["status"] == "ok")
    assert ok_end["output"] == "Hello there!"
    assert "error calling" in capsys.readouterr().out


def test_reasoning_agent_suite_mode_continues_past_a_connection_failure(tmp_path, monkeypatch):
    """`litellm.exceptions.APIConnectionError` (gateway/provider down) is a subclass of `openai.OpenAIError` -
    every exception litellm raises is (verified directly against a running gateway while implementing
    add-litellm-gateway-infra) - so it is caught the same way any other call failure is: the failing case is
    recorded as an error turn and the rest of the suite still runs."""
    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
        return _FakeLiteLLMResponse("Final answer: 5")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    suite = tmp_path / "s.json"
    suite.write_text(
        json.dumps(
            {
                "cases": [
                    {"category": "reasoning", "title": "fails", "prompt": "2+2?"},
                    {"category": "reasoning", "title": "succeeds", "prompt": "2+3?", "expected": "5"},
                ]
            }
        )
    )

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.run_suite(client, None, "http://gateway.local", "vkey", suite)  # must not raise
    client.close(timeout_s=2.0)

    ends = [e for e in received if e["type"] == "turn.end"]
    assert len(ends) == 2
    assert {e["status"] for e in ends} == {"error", "ok"}


def test_reasoning_agent_gateway_failure_never_falls_back_to_a_direct_provider_call(monkeypatch):
    """design.md: a gateway failure fails the call visibly - it must never silently retry the same request
    without the gateway's api_base/api_key, which would mean talking to a provider directly."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    try:
        reasoning_agent.run_once(client, None, "http://gateway.local", "vkey", "2+3?")
    except SystemExit:
        pass
    client.close(timeout_s=2.0)

    # Exactly one completion() attempt (the plan call) - no retry without api_base/api_key that would imply a
    # direct, bypassing-the-gateway call.
    assert len(calls) == 1
    assert calls[0]["api_base"] == "http://gateway.local"


def test_reasoning_agent_suite_mode_sends_expected_answer_as_reference(tmp_path, monkeypatch):
    suite = tmp_path / "s.json"
    suite.write_text(
        json.dumps(
            {
                "cases": [
                    {"category": "reasoning", "title": "r1", "prompt": "2+3?", "expected": "5"},
                    {"category": "classification", "title": "c1", "prompt": "ignored"},
                ]
            }
        )
    )

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse("Final answer: 5")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local",
        "tok",
        transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.run_suite(client, None, "http://gateway.local", "vkey", suite)
    client.close(timeout_s=2.0)

    starts = [e for e in received if e["type"] == "turn.start"]
    assert len(starts) == 1  # only the reasoning case was replayed
    assert starts[0]["reference"] == "5"


# ------------------------------------------------------------------ add-declared-model-fallback
def test_call_llm_passes_fallbacks_only_when_a_fallback_group_is_given(monkeypatch):
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    reasoning_agent.call_llm("http://gateway.local", "vkey", "my-reasoner__reasoning", "hi")
    assert "fallbacks" not in calls[0]

    reasoning_agent.call_llm(
        "http://gateway.local", "vkey", "my-reasoner__reasoning", "hi",
        fallback_group="my-reasoner__reasoning__fallback",
    )
    assert calls[1]["fallbacks"] == ["openai/my-reasoner__reasoning__fallback"]


def test_call_llm_ignores_fallback_group_outside_the_gateway(monkeypatch):
    """No gateway, no fallback mechanism to speak of - `--model` direct calls never pass `fallbacks`."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    reasoning_agent.call_llm(None, None, "ollama_chat/qwen3:8b", "hi", fallback_group="some__fallback")
    assert "fallbacks" not in calls[0]


def test_solve_one_passes_reasoning_and_generation_fallback_groups_to_the_matching_calls(monkeypatch):
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(
        client, "s1", None, "http://gateway.local", "vkey-123", "2+3?",
        reasoning_fallback_group="my-reasoner__reasoning__fallback",
        generation_fallback_group="my-reasoner__generation__fallback",
    )
    client.close(timeout_s=2.0)

    # plan, solve, verify - plan/verify get the reasoning fallback, solve gets the generation fallback
    assert calls[0]["fallbacks"] == ["openai/my-reasoner__reasoning__fallback"]
    assert calls[1]["fallbacks"] == ["openai/my-reasoner__generation__fallback"]
    assert calls[2]["fallbacks"] == ["openai/my-reasoner__reasoning__fallback"]


def test_explicit_model_ignores_fallback_groups_too(monkeypatch):
    """`--model` skips the gateway for all three calls - a fallback group has nothing to mean there either."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(
        client, "s1", "ollama_chat/qwen3:8b", "http://gateway.local", "vkey-123", "2+3?",
        reasoning_fallback_group="my-reasoner__reasoning__fallback",
        generation_fallback_group="my-reasoner__generation__fallback",
    )
    client.close(timeout_s=2.0)

    assert all("fallbacks" not in c for c in calls)


def test_cli_exposes_fallback_group_flags():
    parser = reasoning_agent.build_arg_parser()
    args = parser.parse_args([
        "--platform-url", "http://localhost:8000", "--token", "tok", "--problem", "2+3?",
        "--reasoning-fallback-group", "demo__reasoning__fallback",
        "--generation-fallback-group", "demo__generation__fallback",
    ])
    assert args.reasoning_fallback_group == "demo__reasoning__fallback"
    assert args.generation_fallback_group == "demo__generation__fallback"


def test_cli_fallback_group_flags_default_to_none():
    parser = reasoning_agent.build_arg_parser()
    args = parser.parse_args(["--platform-url", "http://localhost:8000", "--token", "tok", "--problem", "2+3?"])
    assert args.reasoning_fallback_group is None
    assert args.generation_fallback_group is None


# ------------------------------------------------------------------ add-agent-self-discovery
def test_discovery_is_used_when_no_explicit_group_is_given(monkeypatch):
    def fake_whoami(platform_url, token):
        assert platform_url == "http://platform.local"
        assert token == "tok"
        return {"gateway_model_groups": {"reasoning": "my-reasoner__reasoning", "generation": "my-reasoner__generation"}}

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", None, None
    )
    assert reasoning_group == "my-reasoner__reasoning"
    assert generation_group == "my-reasoner__generation"


def test_explicit_override_wins_for_its_own_task_without_consulting_discovery(monkeypatch):
    def fake_whoami(platform_url, token):
        return {"gateway_model_groups": {"reasoning": "discovered__reasoning", "generation": "discovered__generation"}}

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", "explicit__reasoning", None
    )
    assert reasoning_group == "explicit__reasoning"  # the override, not the (different) discovered value
    assert generation_group == "discovered__generation"  # still discovered - no override given for this task


def test_whoami_is_not_called_when_both_groups_are_explicit(monkeypatch):
    def fake_whoami(platform_url, token):
        raise AssertionError("whoami() must not be called when both groups are already explicit")

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", "explicit__reasoning", "explicit__generation"
    )
    assert (reasoning_group, generation_group) == ("explicit__reasoning", "explicit__generation")


def test_failed_discovery_falls_back_to_hardcoded_defaults_with_a_visible_warning(monkeypatch, capsys):
    def fake_whoami(platform_url, token):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", platform_url))

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", None, None
    )
    assert reasoning_group == reasoning_agent.REASONING_MODEL_GROUP
    assert generation_group == reasoning_agent.GENERATION_MODEL_GROUP
    assert "warning" in capsys.readouterr().err.lower()


def test_main_skips_discovery_entirely_when_model_is_explicit(monkeypatch):
    def fake_whoami(platform_url, token):
        raise AssertionError("whoami() must not be called when --model is set")

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)

    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _FakeLiteLLMResponse("...")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    monkeypatch.setattr(
        reasoning_agent, "AgentClient",
        lambda *a, **k: AgentClient(
            "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler([])),
            flush_interval_s=0.02,
        ),
    )
    reasoning_agent.main([
        "--platform-url", "http://platform.local", "--token", "tok",
        "--model", "ollama_chat/qwen3:8b", "--problem", "2+3?",
    ])
    assert calls  # the call still happened - just never through discovery
