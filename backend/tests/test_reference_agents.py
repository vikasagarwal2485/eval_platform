"""Scripted runs of the reference agents against a fake Ollama/gateway and a fake platform (task 7.1/7.2,
`add-reasoning-agent-task-routing`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import openai
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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

    # add-otel-tracing: no more "span" event type - the call's detail is now a real OTel span
    # (test_reference_agents_tracing.py), and its summary reaches turn.end directly.
    types = [e["type"] for e in received]
    assert types.count("turn.start") == 1
    assert types.count("turn.end") == 1
    end = next(e for e in received if e["type"] == "turn.end")
    assert end["output"] == "Hello there!"
    assert end["models"] == ["qwen3:8b"]
    assert end["prompt_tokens"] == 10 and end["completion_tokens"] == 5


def test_chatbot_turn_start_carries_the_system_prompt_in_effect(monkeypatch):
    monkeypatch.setattr(chatbot.httpx, "post", lambda url, json=None, timeout=None: _FakeOllamaResponse("hi"))
    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    chatbot.answer(client, "s1", "qwen3:8b", "http://ollama.local", "be terse", [], "hi")
    client.close(timeout_s=2.0)

    start = next(e for e in received if e["type"] == "turn.start")
    assert start["system_prompt"] == "be terse"


def test_chatbot_turn_start_omits_system_prompt_when_empty(monkeypatch):
    monkeypatch.setattr(chatbot.httpx, "post", lambda url, json=None, timeout=None: _FakeOllamaResponse("hi"))
    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    chatbot.answer(client, "s1", "qwen3:8b", "http://ollama.local", "", [], "hi")
    client.close(timeout_s=2.0)

    start = next(e for e in received if e["type"] == "turn.start")
    assert start["system_prompt"] is None


def test_reasoning_agent_one_problem_produces_four_spans_under_one_turn(monkeypatch):
    """`add-classification-task-routing`: classify is now the first of four calls (was three)."""
    answers = iter(["arithmetic, easy", "1. Do X", "Working: ...", "Final answer: 42"])

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse(next(answers))

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

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
    final = reasoning_agent.solve_one(
        client, "s1", "ollama_chat/qwen3:8b", "http://gateway.local", None, "2+3?", reference="5"
    )
    client.close(timeout_s=2.0)
    provider.shutdown()

    assert "42" in final
    turn_id = {e["turn_id"] for e in received}
    assert len(turn_id) == 1  # every event belongs to the same turn
    # add-otel-tracing: the four calls are now four real OTel spans, not JSON "span" events
    call_spans = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert len(call_spans) == 4
    trace_ids = {format(s.context.trace_id, "032x") for s in call_spans}
    assert len(trace_ids) == 1  # all four under one trace
    # `kind` is the only thing that tells the four (identically-named, identically-modeled here)
    # spans apart - without it there's no way to see which call was classify/plan/solve/verify
    by_start = sorted(call_spans, key=lambda s: s.start_time)
    assert [s.attributes["eval.kind"] for s in by_start] == ["classify", "plan", "solve", "verify"]
    start = next(e for e in received if e["type"] == "turn.start")
    assert start["reference"] == "5"
    end = next(e for e in received if e["type"] == "turn.end")
    assert end["trace_id"] in trace_ids


def test_reasoning_agent_default_mode_routes_classify_plan_verify_and_solve_to_different_task_model_groups(
    monkeypatch,
):
    """`model=None` (the CLI default) - classify addresses `CLASSIFICATION_MODEL_GROUP`, plan/verify address
    `REASONING_MODEL_GROUP`, solve addresses `GENERATION_MODEL_GROUP`, each prefixed `openai/` and sent through
    the gateway's `api_base` (the SDK needs that prefix to treat an arbitrary `api_base` as an OpenAI-compatible
    endpoint - verified directly against a running gateway while implementing add-litellm-gateway-infra; a bare
    group name fails there)."""
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
        f"openai/{reasoning_agent.CLASSIFICATION_MODEL_GROUP}",
        f"openai/{reasoning_agent.REASONING_MODEL_GROUP}",
        f"openai/{reasoning_agent.GENERATION_MODEL_GROUP}",
        f"openai/{reasoning_agent.REASONING_MODEL_GROUP}",
    ]
    assert all(c["api_base"] == "http://gateway.local" for c in calls)
    assert all(c["api_key"] == "vkey-123" for c in calls)


def test_reasoning_generation_and_classification_model_groups_are_overridable(monkeypatch):
    """--reasoning-model-group/--generation-model-group/--classification-model-group (all three, consistently -
    `add-classification-task-routing`) let an operator point at an agent registered under any name, overriding
    self-discovery for that task entirely."""
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
        classification_group="my-reasoner__classification",
    )
    client.close(timeout_s=2.0)

    assert [c["model"] for c in calls] == [
        "openai/my-reasoner__classification",
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
        classification_group="demo__classification",
    )
    client.close(timeout_s=2.0)

    assert calls[0]["model"] == "openai/demo__classification"
    assert calls[1]["model"] == "openai/demo__reasoning"
    assert calls[2]["model"] == "openai/demo__generation"


def test_reasoning_agent_explicit_model_skips_the_gateway_for_all_four_calls(monkeypatch):
    """`--model` overrides all four calls to one literal model string with no gateway involved - local testing
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

    assert [c["model"] for c in calls] == ["ollama_chat/qwen3:8b"] * 4
    assert all("api_base" not in c for c in calls)
    assert all("api_key" not in c for c in calls)


def test_reasoning_agent_records_the_concrete_model_not_the_group_alias(monkeypatch):
    """`turn.end`'s `models` must list the real deployment that answered (`ollama_chat/qwen3:8b`), never the
    gateway's routing alias (`reasoning-agent__reasoning`) - `plan_turn_evaluators`/`same_model`/`same_family`
    key off this for the never-self-judge invariant, and an alias would break that check silently."""

    def fake_completion(**kwargs):
        return _FakeLiteLLMResponse("...", concrete_model="ollama_chat/qwen3:8b")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

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
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?")
    client.close(timeout_s=2.0)
    provider.shutdown()

    call_spans = [s for s in exp.get_finished_spans() if s.name == "gen_ai.chat"]
    assert len(call_spans) == 4
    models = {s.attributes["gen_ai.request.model"] for s in call_spans}
    assert models == {"ollama_chat/qwen3:8b"}
    assert reasoning_agent.REASONING_MODEL_GROUP not in models
    assert reasoning_agent.GENERATION_MODEL_GROUP not in models
    assert reasoning_agent.CLASSIFICATION_MODEL_GROUP not in models

    end = next(e for e in received if e["type"] == "turn.end")
    assert end["models"] == ["ollama_chat/qwen3:8b"]  # de-duplicated across all four calls


def test_call_llm_sends_a_system_message_when_given(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _FakeLiteLLMResponse("ok")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    reasoning_agent.call_llm(None, None, "qwen3:8b", "solve this", system_prompt="be terse")
    assert captured["messages"][0] == {"role": "system", "content": "be terse"}
    assert captured["messages"][1] == {"role": "user", "content": "solve this"}


def test_call_llm_omits_system_message_by_default(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _FakeLiteLLMResponse("ok")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    reasoning_agent.call_llm(None, None, "qwen3:8b", "solve this")
    assert captured["messages"] == [{"role": "user", "content": "solve this"}]


def test_solve_one_applies_system_prompt_to_plan_solve_verify_not_classify(monkeypatch):
    seen_system_messages = []

    def fake_completion(**kwargs):
        system = next((m["content"] for m in kwargs["messages"] if m["role"] == "system"), None)
        seen_system_messages.append(system)
        return _FakeLiteLLMResponse("answer")

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler([])), flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(
        client, "s1", None, "http://gateway.local", None, "2+3?", system_prompt="be terse",
    )
    client.close(timeout_s=2.0)
    # classify, plan, solve, verify, in that order
    assert seen_system_messages == [None, "be terse", "be terse", "be terse"]


def test_reasoning_agent_turn_start_carries_the_system_prompt(monkeypatch):
    monkeypatch.setattr(reasoning_agent.litellm, "completion", lambda **kwargs: _FakeLiteLLMResponse("answer"))
    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?", system_prompt="be terse")
    client.close(timeout_s=2.0)

    start = next(e for e in received if e["type"] == "turn.start")
    assert start["system_prompt"] == "be terse"


def test_reasoning_agent_turn_start_omits_system_prompt_by_default(monkeypatch):
    monkeypatch.setattr(reasoning_agent.litellm, "completion", lambda **kwargs: _FakeLiteLLMResponse("answer"))
    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?")
    client.close(timeout_s=2.0)

    start = next(e for e in received if e["type"] == "turn.start")
    assert start["system_prompt"] is None


def test_reasoning_agent_compose_system_prompt_prepends_skills_in_order():
    assert reasoning_agent.compose_system_prompt("base", ["A", "B"]) == "A\n\nB\n\nbase"


def test_reasoning_agent_compose_system_prompt_with_nothing_returns_none():
    assert reasoning_agent.compose_system_prompt(None, []) is None


def test_reasoning_agent_fetch_skill_returns_instructions(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(200, json={"instructions": "Think."}, request=httpx.Request("GET", url))

    monkeypatch.setattr(reasoning_agent.httpx, "get", fake_get)
    assert reasoning_agent._fetch_skill("http://platform.local", "tok", "step-by-step") == "Think."


def test_cli_exposes_system_prompt_and_skill_flags():
    args = reasoning_agent.build_arg_parser().parse_args(
        ["--platform-url", "http://x", "--token", "t", "--problem", "p",
         "--system-prompt", "be terse", "--skill", "a", "--skill", "b"]
    )
    assert args.system_prompt == "be terse"
    assert args.skills == ["a", "b"]


def test_cli_task_is_an_alias_for_problem():
    args = reasoning_agent.build_arg_parser().parse_args(
        ["--platform-url", "http://x", "--token", "t", "--task", "a one-shot task"]
    )
    assert args.problem == "a one-shot task"


def test_cli_system_prompt_and_skill_default_to_none_and_empty():
    args = reasoning_agent.build_arg_parser().parse_args(
        ["--platform-url", "http://x", "--token", "t", "--problem", "p"]
    )
    assert args.system_prompt is None
    assert args.skills == []


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
    assert usage["thinking"] is None  # no reasoning_content on this fake response


def test_call_llm_extracts_reasoning_content_as_thinking(monkeypatch):
    """add-agent-playground: litellm's Ollama transformation remaps Ollama's own `message.thinking`
    to `message.reasoning_content` on the response object - verified directly against the installed
    litellm package (llms/ollama/chat/transformation.py)."""

    def fake_completion(**kwargs):
        resp = _FakeLiteLLMResponse("hello", concrete_model="ollama_chat/qwen3:8b")
        resp.choices[0].message.reasoning_content = "let me think..."
        return resp

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    _, usage = reasoning_agent.call_llm("http://gateway.local", None, "reasoning-agent__reasoning", "hi")
    assert usage["thinking"] == "let me think..."


def test_solve_one_forwards_thinking_to_plan_solve_verify_but_not_classify(monkeypatch):
    def fake_completion(**kwargs):
        resp = _FakeLiteLLMResponse("answer")
        resp.choices[0].message.reasoning_content = "thinking about it"
        return resp

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)
    captured_thinking = {}
    real_span = reasoning_agent._span

    def spy_span(t, model, output, usage, *, kind, thinking=None):
        captured_thinking[kind] = thinking
        real_span(t, model, output, usage, kind=kind, thinking=thinking)

    monkeypatch.setattr(reasoning_agent, "_span", spy_span)
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler([])), flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?")
    client.close(timeout_s=2.0)

    assert captured_thinking["classify"] is None
    assert captured_thinking["plan"] == "thinking about it"
    assert captured_thinking["solve"] == "thinking about it"
    assert captured_thinking["verify"] == "thinking about it"


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


def test_compose_system_prompt_prepends_skills_in_order():
    assert chatbot.compose_system_prompt("base", ["skill A", "skill B"]) == "skill A\n\nskill B\n\nbase"


def test_compose_system_prompt_with_no_skills_is_unchanged():
    assert chatbot.compose_system_prompt("base", []) == "base"


def test_fetch_skill_returns_instructions(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url == "http://platform.local/api/ingest/v1/skills/step-by-step"
        assert headers == {"Authorization": "Bearer tok"}
        return httpx.Response(
            200,
            json={"name": "step-by-step", "description": "d", "instructions": "Think."},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(chatbot.httpx, "get", fake_get)
    assert chatbot._fetch_skill("http://platform.local", "tok", "step-by-step") == "Think."


def test_fetch_skill_unknown_name_raises_system_exit(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(404, json={"detail": {"message": "not found"}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(chatbot.httpx, "get", fake_get)
    with pytest.raises(SystemExit) as exc_info:
        chatbot._fetch_skill("http://platform.local", "tok", "nope")
    assert "nope" in str(exc_info.value)


def test_run_task_answers_once_and_returns_output(monkeypatch):
    monkeypatch.setattr(chatbot.httpx, "post", lambda url, json=None, timeout=None: _FakeOllamaResponse("hi there"))
    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    out = chatbot.run_task(client, "qwen3:8b", "http://ollama.local", chatbot.DEFAULT_SYSTEM_PROMPT, "hello?")
    client.close(timeout_s=2.0)
    assert out == "hi there"
    ends = [e for e in received if e["type"] == "turn.end"]
    assert len(ends) == 1 and ends[0]["output"] == "hi there"


def test_cli_exposes_skill_and_task_flags():
    args = chatbot.build_arg_parser().parse_args(
        [
            "--platform-url", "http://x", "--token", "t",
            "--skill", "a", "--skill", "b", "--task", "hello",
        ]
    )
    assert args.skills == ["a", "b"]
    assert args.task == "hello"


def test_cli_skill_and_task_default_to_empty_and_none():
    args = chatbot.build_arg_parser().parse_args(["--platform-url", "http://x", "--token", "t"])
    assert args.skills == []
    assert args.task is None


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


def test_solve_one_passes_reasoning_generation_and_classification_fallback_groups_to_the_matching_calls(
    monkeypatch,
):
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
        classification_fallback_group="my-reasoner__classification__fallback",
    )
    client.close(timeout_s=2.0)

    # classify, plan, solve, verify - classify gets its own fallback, plan/verify get the reasoning fallback,
    # solve gets the generation fallback
    assert calls[0]["fallbacks"] == ["openai/my-reasoner__classification__fallback"]
    assert calls[1]["fallbacks"] == ["openai/my-reasoner__reasoning__fallback"]
    assert calls[2]["fallbacks"] == ["openai/my-reasoner__generation__fallback"]
    assert calls[3]["fallbacks"] == ["openai/my-reasoner__reasoning__fallback"]


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


# ------------------------------------------------------------------ add-classification-task-routing
def test_cli_exposes_classification_group_and_fallback_flags():
    parser = reasoning_agent.build_arg_parser()
    args = parser.parse_args([
        "--platform-url", "http://localhost:8000", "--token", "tok", "--problem", "2+3?",
        "--classification-model-group", "demo__classification",
        "--classification-fallback-group", "demo__classification__fallback",
    ])
    assert args.classification_model_group == "demo__classification"
    assert args.classification_fallback_group == "demo__classification__fallback"


def test_cli_classification_flags_default_to_none():
    parser = reasoning_agent.build_arg_parser()
    args = parser.parse_args(["--platform-url", "http://localhost:8000", "--token", "tok", "--problem", "2+3?"])
    assert args.classification_model_group is None
    assert args.classification_fallback_group is None


def test_classification_result_never_changes_plan_solve_verify_prompts(monkeypatch):
    """design.md Non-Goals: the classification call's output is recorded, not acted upon - plan/solve/verify's
    prompts must come out identical regardless of what classify() returns. Each call gets a distinct,
    identifiable response so a real leak (vs. a later call's own legitimate output, e.g. plan's own text
    flowing into solve's prompt) can be told apart."""
    responses = iter(["UNEXPECTED_CLASSIFICATION_MARKER_XYZ", "the plan", "the solution", "the verified answer"])
    prompts_seen: list[str] = []

    def fake_completion(**kwargs):
        prompts_seen.append(kwargs["messages"][-1]["content"])
        return _FakeLiteLLMResponse(next(responses))

    monkeypatch.setattr(reasoning_agent.litellm, "completion", fake_completion)

    received: list = []
    client = AgentClient(
        "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)),
        flush_interval_s=0.02,
    )
    reasoning_agent.solve_one(client, "s1", None, "http://gateway.local", None, "2+3?")
    client.close(timeout_s=2.0)

    assert len(prompts_seen) == 4
    classify_prompt, plan_prompt, solve_prompt, verify_prompt = prompts_seen
    assert "UNEXPECTED_CLASSIFICATION_MARKER_XYZ" not in plan_prompt
    assert "UNEXPECTED_CLASSIFICATION_MARKER_XYZ" not in solve_prompt
    assert "UNEXPECTED_CLASSIFICATION_MARKER_XYZ" not in verify_prompt
    # plan's prompt is exactly what it was before classification existed - built only from `problem`
    assert plan_prompt == reasoning_agent.PLAN_PROMPT.format(problem="2+3?")


# ------------------------------------------------------------------ add-agent-self-discovery
def test_discovery_is_used_when_no_explicit_group_is_given(monkeypatch):
    def fake_whoami(platform_url, token):
        assert platform_url == "http://platform.local"
        assert token == "tok"
        return {
            "gateway_model_groups": {
                "reasoning": "my-reasoner__reasoning",
                "generation": "my-reasoner__generation",
                "classification": "my-reasoner__classification",
            }
        }

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group, classification_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", None, None
    )
    assert reasoning_group == "my-reasoner__reasoning"
    assert generation_group == "my-reasoner__generation"
    assert classification_group == "my-reasoner__classification"


def test_explicit_override_wins_for_its_own_task_without_consulting_discovery(monkeypatch):
    def fake_whoami(platform_url, token):
        return {
            "gateway_model_groups": {
                "reasoning": "discovered__reasoning",
                "generation": "discovered__generation",
                "classification": "discovered__classification",
            }
        }

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group, classification_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", "explicit__reasoning", None
    )
    assert reasoning_group == "explicit__reasoning"  # the override, not the (different) discovered value
    assert generation_group == "discovered__generation"  # still discovered - no override given for this task
    assert classification_group == "discovered__classification"  # likewise discovered


def test_whoami_is_not_called_when_all_three_groups_are_explicit(monkeypatch):
    def fake_whoami(platform_url, token):
        raise AssertionError("whoami() must not be called when all three groups are already explicit")

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group, classification_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", "explicit__reasoning", "explicit__generation", "explicit__classification"
    )
    assert (reasoning_group, generation_group, classification_group) == (
        "explicit__reasoning", "explicit__generation", "explicit__classification",
    )


def test_whoami_is_still_called_when_only_two_of_three_groups_are_explicit(monkeypatch):
    """Discovery is skipped only once EVERY task has an explicit override - not as soon as some do."""
    calls = {"n": 0}

    def fake_whoami(platform_url, token):
        calls["n"] += 1
        return {"gateway_model_groups": {"classification": "discovered__classification"}}

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    _, _, classification_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", "explicit__reasoning", "explicit__generation", None
    )
    assert calls["n"] == 1
    assert classification_group == "discovered__classification"


def test_failed_discovery_falls_back_to_hardcoded_defaults_with_a_visible_warning(monkeypatch, capsys):
    def fake_whoami(platform_url, token):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", platform_url))

    monkeypatch.setattr(reasoning_agent, "whoami", fake_whoami)
    reasoning_group, generation_group, classification_group = reasoning_agent._resolve_model_groups(
        "http://platform.local", "tok", None, None
    )
    assert reasoning_group == reasoning_agent.REASONING_MODEL_GROUP
    assert generation_group == reasoning_agent.GENERATION_MODEL_GROUP
    assert classification_group == reasoning_agent.CLASSIFICATION_MODEL_GROUP
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


def test_main_wires_a_fixed_workflow_name_into_the_agent_client(monkeypatch):
    """add-otel-tracing: reasoning_agent.py's turn is a genuine four-step pipeline, unlike
    chatbot.py's single call - `main()` always passes a literal `workflow_name` for it."""
    captured = {}

    def fake_agent_client(*_a, **kw):
        captured.update(kw)
        return AgentClient(
            "http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler([])),
            flush_interval_s=0.02,
        )

    monkeypatch.setattr(reasoning_agent, "AgentClient", fake_agent_client)
    monkeypatch.setattr(reasoning_agent.litellm, "completion", lambda **kw: _FakeLiteLLMResponse("..."))
    reasoning_agent.main([
        "--platform-url", "http://platform.local", "--token", "tok",
        "--model", "ollama_chat/qwen3:8b", "--problem", "2+3?",
    ])
    assert captured["workflow_name"] == "reasoning-pipeline"


# ------------------------------------------------------------------ add-otel-tracing: --otel-endpoint
def test_otel_endpoint_falls_back_to_the_env_var_when_the_flag_is_omitted(monkeypatch):
    """Setting EVAL_OTEL_ENDPOINT in the shell - the same env var the platform backend itself reads -
    must be enough on its own; the flag should never be required just to match what's already set."""
    monkeypatch.setenv("EVAL_OTEL_ENDPOINT", "localhost:4317")

    chatbot_args = chatbot.build_arg_parser().parse_args(
        ["--platform-url", "http://platform.local", "--token", "tok"]
    )
    assert chatbot_args.otel_endpoint == "localhost:4317"

    reasoning_args = reasoning_agent.build_arg_parser().parse_args(
        ["--platform-url", "http://platform.local", "--token", "tok", "--problem", "2+3?"]
    )
    assert reasoning_args.otel_endpoint == "localhost:4317"


def test_otel_endpoint_flag_overrides_the_env_var(monkeypatch):
    monkeypatch.setenv("EVAL_OTEL_ENDPOINT", "localhost:4317")
    args = reasoning_agent.build_arg_parser().parse_args(
        [
            "--platform-url", "http://platform.local", "--token", "tok", "--problem", "2+3?",
            "--otel-endpoint", "collector.other.host:4317",
        ]
    )
    assert args.otel_endpoint == "collector.other.host:4317"


def test_otel_endpoint_defaults_to_none_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("EVAL_OTEL_ENDPOINT", raising=False)
    chatbot_args = chatbot.build_arg_parser().parse_args(
        ["--platform-url", "http://platform.local", "--token", "tok"]
    )
    assert chatbot_args.otel_endpoint is None
    reasoning_args = reasoning_agent.build_arg_parser().parse_args(
        ["--platform-url", "http://platform.local", "--token", "tok", "--problem", "2+3?"]
    )
    assert reasoning_args.otel_endpoint is None
