"""8.1: end-to-end coverage of the live-agent-evaluation loop through the real app (fake Ollama, fake OpenAI,
real background workers) - registering an agent and rotating its token, out-of-order and replayed ingest, a
two-evaluator panel with one unavailable evaluator, a benchmark run pausing evaluation, re-evaluation creating a
new attempt, and export including per-evaluator scores. Needs no external network access."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from tests.fakes import FakeOllama, make_stream, make_tag
from tests.helpers import GEN, make_responder, wait_for


def _criteria_in(user_text: str) -> list[str]:
    """Criterion names from a judge prompt's `CRITERIA:` section (see `build_judge_messages`), so the fake judge
    can answer whatever rubric is actually asked - the chatbot rubric here has 4 criteria, not the 2-criterion
    generation rubric `tests.helpers.judge_reply` assumes."""
    section = user_text.split("CRITERIA:\n", 1)[-1]
    names: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            if names:
                break
            continue
        names.append(line[2:].split(":", 1)[0].strip())
    return names


def _agent_aware_responder():
    base = make_responder()

    def responder(model, messages, options):
        if messages and messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
            names = _criteria_in(messages[-1]["content"])
            return make_stream(json.dumps({"scores": {n: {"score": 5, "reason": "ok"} for n in names}}))
        return base(model, messages, options)

    return responder


def _wait_until(predicate, timeout=15.0, interval=0.05):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError("condition was not met in time")


def test_full_agent_evaluation_lifecycle(settings, file_session_factory, monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)  # the cloud evaluator's key is deliberately never set
    fake = FakeOllama(
        [make_tag("author:1"), make_tag("judge:1"), make_tag("bench:1")], _agent_aware_responder(), chunk_delay_s=0.1
    )
    with file_session_factory() as s:
        provider = repo.create_provider(
            s, kind="openai", name="oa", key_env="MISSING_KEY", base_url="http://unused.invalid",
            ack_at=datetime.now(UTC),
        )
        repo.add_registered_model(s, provider.id, "gpt-4o")
        s.commit()

    app = create_app(settings, ollama=fake, session_factory=file_session_factory)
    with TestClient(app) as client:
        # ---- register, rotate token
        r = client.post(
            "/api/agents",
            json={
                "name": "bot", "kind": "chatbot", "declared_model": "author:1",
                "eval_config": {"evaluators": ["judge:1", "@oa/gpt-4o"], "quiet_period_s": 0},
                "provider_acks": ["oa"],
            },
        )
        assert r.status_code == 201, r.text
        agent = r.json()
        r = client.post(f"/api/agents/{agent['id']}/rotate-token")
        token = r.json()["token"]
        assert token != agent["token"]

        # ---- start a slow benchmark run before the agent turn exists, so it is "measuring" throughout ingest
        run = client.post("/api/runs", json={"models": ["bench:1"], "adhoc_cases": [GEN], "config": {"warmup": False}})
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]

        # ---- ingest one turn, out of order (end and span arrive before start), in a single batch
        events = [
            {"v": 1, "event_id": "e3", "session_id": "s1", "turn_id": "t1", "type": "turn.end", "status": "ok", "output": "hello"},
            {
                "v": 1, "event_id": "e2", "session_id": "s1", "turn_id": "t1", "type": "span", "span_id": "sp1",
                "kind": "llm", "model": "author:1", "output": "hello",
            },
            {"v": 1, "event_id": "e1", "session_id": "s1", "turn_id": "t1", "type": "turn.start", "input": "hi"},
        ]
        r = client.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"accepted": 3, "duplicates": 0, "rejected": []}
        turn = client.get(f"/api/agents/{agent['id']}/turns").json()[0]
        assert turn["input"] == "hi" and turn["status"] == "ok" and turn["models"] == ["author:1"]

        # ---- replay the exact same batch: every event is now a duplicate
        r = client.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})
        assert r.json() == {"accepted": 0, "duplicates": 3, "rejected": []}

        # ---- while the benchmark run is still active, the turn's evaluation must not have finished
        first_look = client.get(f"/api/agents/{agent['id']}/turns/{turn['id']}").json()["latest_evaluation"]
        assert first_look["status"] in ("pending",)

        wait_for(client, run_id, timeout=30)  # let the benchmark run finish

        # ---- now the evaluation queue drains: judge:1 (available) judges it, @oa/gpt-4o (no key) is skipped
        evaluated = _wait_until(
            lambda: (e := client.get(f"/api/agents/{agent['id']}/turns/{turn['id']}").json()["latest_evaluation"])
            and e["status"] in ("done", "error")
            and e,
            timeout=30,
        )
        assert evaluated["status"] == "done"
        detail = client.get(f"/api/agents/{agent['id']}/turns/{turn['id']}").json()
        judges = {j["judge_model"] for j in detail["evaluations"][-1]["judgements"]}
        assert judges == {"judge:1"}  # the unavailable evaluator was skipped, not fabricated as a failure

        # ---- re-evaluate: a new attempt, history kept
        r = client.post(f"/api/agents/{agent['id']}/turns/{turn['id']}/evaluate", json={"evaluators": ["judge:1"]})
        assert r.status_code == 202
        assert r.json()["attempt_no"] == 2

        def _second_attempt_done():
            full = client.get(f"/api/agents/{agent['id']}/turns/{turn['id']}").json()
            evals = full["evaluations"]
            return full if len(evals) == 2 and evals[-1]["status"] == "done" else None

        full = _wait_until(_second_attempt_done, timeout=30)
        assert len(full["evaluations"]) == 2  # both attempts still readable
        assert full["evaluations"][0]["status"] == "done"  # the original attempt was not overwritten

        # ---- export includes per-evaluator scores
        csv_text = client.get(f"/api/agents/{agent['id']}/export?format=csv").text
        assert "judge:1=" in csv_text
        json_body = client.get(f"/api/agents/{agent['id']}/export?format=json").json()
        assert any("judge:1=" in row["judges"] for row in json_body["turns"])
