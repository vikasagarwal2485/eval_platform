"""Scripted runs of the reference agents against a fake Ollama and a fake platform (task 7.1/7.2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

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
    client = AgentClient("http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)), flush_interval_s=0.02)
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

    def fake_post(url, json=None, timeout=None):
        return _FakeOllamaResponse(next(answers))

    monkeypatch.setattr(reasoning_agent.httpx, "post", fake_post)

    received: list = []
    client = AgentClient("http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)), flush_interval_s=0.02)
    final = reasoning_agent.solve_one(client, "s1", "qwen3:8b", "http://ollama.local", "2+3?", reference="5")
    client.close(timeout_s=2.0)

    assert "42" in final
    turn_id = {e["turn_id"] for e in received}
    assert len(turn_id) == 1  # every event belongs to the same turn
    spans = [e for e in received if e["type"] == "span"]
    assert len(spans) == 3
    start = next(e for e in received if e["type"] == "turn.start")
    assert start["reference"] == "5"


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

    def fake_post(url, json=None, timeout=None):
        return _FakeOllamaResponse("Final answer: 5")

    monkeypatch.setattr(reasoning_agent.httpx, "post", fake_post)

    received: list = []
    client = AgentClient("http://platform.local", "tok", transport=httpx.MockTransport(_platform_handler(received)), flush_interval_s=0.02)
    reasoning_agent.run_suite(client, "qwen3:8b", "http://ollama.local", suite)
    client.close(timeout_s=2.0)

    starts = [e for e in received if e["type"] == "turn.start"]
    assert len(starts) == 1  # only the reasoning case was replayed
    assert starts[0]["reference"] == "5"
