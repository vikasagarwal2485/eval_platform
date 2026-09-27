"""8.2: no API key value used by a hosted evaluator may reach the database, any agent API response, the agent
export, agent SSE state, logs or stored errors. Mirrors tests/test_secret_leaks.py for the benchmark-run side."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from tests.fake_providers import FakeOpenAI, Step
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder

SENTINEL = "sk-proj-LEAKCHECK0123456789abcdefghijKLMN"
PARTIAL = SENTINEL[10:30]


def find_leaks(text: str) -> list[str]:
    return [what for what, needle in (("full key", SENTINEL), ("partial key", PARTIAL)) if needle in text]


def db_bytes(sf) -> bytes:
    path = sf.kw["bind"].url.database
    data = b""
    for suffix in ("", "-wal", "-shm"):
        try:
            data += open(path + suffix, "rb").read()
        except FileNotFoundError:
            pass
    return data


def stored_errors(sf) -> list[str]:
    from sqlalchemy import select

    from app.models import AgentTurn, TurnEvaluation, TurnJudgement

    with sf() as s:
        texts = [str(t.error) for t in s.scalars(select(AgentTurn))]
        texts += [str(e.detail) for e in s.scalars(select(TurnEvaluation))]
        texts += [str(j.detail) for j in s.scalars(select(TurnJudgement))]
    return texts


def collect_everything(client, agent_id, turn_ids) -> dict[str, str]:
    out: dict[str, str] = {}
    pid = client.get("/api/providers").json()[0]["id"]
    urls = [
        "/api/providers", f"/api/providers/{pid}", "/api/health",
        "/api/agents", f"/api/agents/{agent_id}", f"/api/agents/{agent_id}/turns",
        f"/api/agents/{agent_id}/summary", f"/api/agents/{agent_id}/attention",
        f"/api/agents/{agent_id}/export?format=csv", f"/api/agents/{agent_id}/export?format=json",
    ]
    for tid in turn_ids:
        urls.append(f"/api/agents/{agent_id}/turns/{tid}")
    for u in urls:
        out[u] = client.get(u).text
    out["test-connection"] = client.post(f"/api/providers/{pid}/test").text
    return out


def _wait_for_evaluation(client, agent_id, turn_id, timeout=30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        turn = client.get(f"/api/agents/{agent_id}/turns/{turn_id}").json()
        latest = turn.get("latest_evaluation")
        if latest and latest["status"] in ("done", "error", "skipped"):
            return latest
        time.sleep(0.05)
    raise AssertionError(f"turn {turn_id} evaluation did not finish in time")


def _ingest(client, token, ext) -> None:
    events = [
        {"v": 1, "event_id": f"{ext}s", "session_id": "s1", "turn_id": ext, "type": "turn.start", "input": "hi"},
        {
            "v": 1, "event_id": f"{ext}sp", "session_id": "s1", "turn_id": ext, "type": "span", "span_id": f"{ext}sp1",
            "kind": "llm", "model": "author:1", "output": "hello",
        },
        {"v": 1, "event_id": f"{ext}e", "session_id": "s1", "turn_id": ext, "type": "turn.end", "status": "ok", "output": "hello"},
    ]
    r = client.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


def test_no_key_reaches_agent_api_export_db_or_stored_errors(settings, file_session_factory, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("SENTINEL_KEY", SENTINEL)
    oa = FakeOpenAI()
    oa.expected_key = SENTINEL
    url = oa.start()
    try:
        with file_session_factory() as s:
            provider = repo.create_provider(
                s, kind="openai", name="oa", key_env="SENTINEL_KEY", base_url=url, ack_at=datetime.now(UTC)
            )
            repo.add_registered_model(s, provider.id, "gpt-4o")
            s.commit()

        fake = FakeOllama([make_tag("author:1")], make_responder())
        app = create_app(settings, ollama=fake, session_factory=file_session_factory)
        with TestClient(app) as client:
            r = client.post(
                "/api/agents",
                json={
                    "name": "bot", "kind": "chatbot", "declared_model": "author:1",
                    "eval_config": {"evaluators": ["@oa/gpt-4o"], "quiet_period_s": 0},
                    "provider_acks": ["oa"],
                },
            )
            assert r.status_code == 201, r.text
            agent = r.json()

            # First turn: the evaluator fails and echoes the key back (as a real provider error sometimes does).
            oa.script.append(Step(kind="status", status=401, body={"error": {"message": f"Incorrect API key: {SENTINEL}"}}))
            _ingest(client, agent["token"], "t1")
            first = _wait_for_evaluation(client, agent["id"], client.get(f"/api/agents/{agent['id']}/turns").json()[0]["id"])
            assert first["status"] == "error"  # the failure really happened - else this test proves nothing

            # Second turn: the evaluator succeeds normally.
            _ingest(client, agent["token"], "t2")
            turns = client.get(f"/api/agents/{agent['id']}/turns").json()
            turn_ids = [t["id"] for t in turns]
            for tid in turn_ids:
                _wait_for_evaluation(client, agent["id"], tid)

            pages = collect_everything(client, agent["id"], turn_ids)

        for url_, text in pages.items():
            leaks = find_leaks(text)
            assert not leaks, f"{leaks} leaked in {url_}: {text[:500]}"

        leaks = find_leaks(db_bytes(file_session_factory).decode("utf-8", "replace"))
        assert not leaks, f"{leaks} leaked in the database file"

        for text in stored_errors(file_session_factory):
            leaks = find_leaks(text)
            assert not leaks, f"{leaks} leaked in a stored error: {text[:500]}"

        for record in caplog.records:
            leaks = find_leaks(record.getMessage())
            assert not leaks, f"{leaks} leaked in a log line: {record.getMessage()[:500]}"

        assert oa.requests  # the fake evaluator really was called (the key must reach it, just nowhere else)
    finally:
        oa.stop()


def test_fails_when_a_leak_is_deliberately_introduced():
    """The test harness itself catches a leak: sanity check that `find_leaks` is not a no-op."""
    assert find_leaks(f"error calling provider: key was {SENTINEL}") == ["full key", "partial key"]
    assert find_leaks("no secrets here") == []
