"""Shared helpers for run/orchestration tests."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama, make_stream, make_tag

TERMINAL = ("completed", "cancelled", "failed")

CLS = dict(
    category="classification", title="c", prompt="I love it", labels=["positive", "negative"], expected="positive"
)
REA = dict(category="reasoning", title="r", prompt="What is 2+3?", expected="5", comparison="numeric")
GEN = dict(
    category="generation",
    title="g",
    prompt="Write a haiku about rain",
    rubric=[{"name": "Relevance"}, {"name": "Fluency"}],
    constraints={"max_words": 50},
)


def judge_reply(a=4, b=4):
    return json.dumps({"scores": {"Relevance": {"score": a, "reason": "r"}, "Fluency": {"score": b, "reason": "f"}}})


def make_responder(answers: dict[str, dict[str, str]] | None = None, judge=judge_reply):
    """answers: model -> {substring of user prompt: reply}. Judge requests are recognised by their system prompt."""
    answers = answers or {}

    def responder(model, messages, options):
        if messages and messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
            return make_stream(judge())
        user = messages[-1]["content"]
        if user.startswith("Reply with the single word"):
            return make_stream("OK", eval_count=1, load_duration_ns=2_000_000_000)
        for key, reply in answers.get(model, {}).items():
            if key in user:
                return make_stream(reply)
        return make_stream("positive" if "labels" in user else "Final answer: 5")

    return responder


def new_client(settings, session_factory, fake: FakeOllama) -> TestClient:
    return TestClient(create_app(settings, ollama=fake, session_factory=session_factory))


def wait_for(client: TestClient, run_id: int, statuses=TERMINAL, timeout=15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses and not run.get("busy"):
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}; last: {run['status']}")


def start_run(client, models, cases, **kw):
    body = {"models": models, "adhoc_cases": cases, **kw}
    r = client.post("/api/runs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def two_models(**kw):
    return [make_tag("a:1", **kw), make_tag("b:1", **kw)]
