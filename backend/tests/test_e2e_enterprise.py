"""7.1: end-to-end over the real HTTP API, with a fake Ollama and fake OpenAI/Anthropic servers.

Covers: registering providers and models through `/api/providers` (never a real key), a mixed
local-plus-cloud run, a hosted single judge over local models, cross-model judging across mixed
models, an authentication failure isolated to one provider, and CSV/JSON export with provider
columns. Needs no real key: the fake servers check a fake value the test sets in the environment.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_ollama_server import running_fake_ollama
from tests.fake_providers import FakeAnthropic, FakeOpenAI
from tests.helpers import wait_for

FAKE_KEY = "test-key-123"  # matches FakeOpenAI/FakeAnthropic.expected_key

GEN_CASE = {
    "category": "generation",
    "title": "haiku",
    "prompt": "Write a haiku about rain",
    "rubric": [{"name": "Relevance"}, {"name": "Fluency"}],
}
CLS_CASE = {
    "category": "classification",
    "title": "sentiment",
    "prompt": "Classify: I love it",
    "labels": ["positive", "negative"],
    "expected": "positive",
}


@pytest.fixture
def stack(settings, file_session_factory, monkeypatch):
    """A real FastAPI app wired to a fake Ollama and fake OpenAI/Anthropic servers, all over real HTTP."""
    monkeypatch.setenv("OA_KEY", FAKE_KEY)
    monkeypatch.setenv("AN_KEY", FAKE_KEY)
    oa, an = FakeOpenAI(), FakeAnthropic()
    oa_url, an_url = oa.start(), an.start()
    oa.answer = an.answer = "Rain taps the glass, soft and slow tonight"
    with running_fake_ollama() as (ollama, ollama_url):
        s = dataclasses.replace(settings, ollama_base_url=ollama_url, request_timeout_s=20)
        with TestClient(create_app(s, session_factory=file_session_factory)) as client:
            yield client, ollama, oa, an, oa_url, an_url
    oa.stop()
    an.stop()


def register_provider(client, kind: str, name: str, key_env: str, base_url: str) -> int:
    r = client.post(
        "/api/providers",
        json={
            "kind": kind,
            "name": name,
            "key_env": key_env,
            "base_url": base_url,
            "acknowledge_data_sharing": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_model(client, provider_id: int, model_id: str, *, reasoning: bool = False) -> str:
    r = client.post(f"/api/providers/{provider_id}/models", json={"model_id": model_id, "reasoning": reasoning})
    assert r.status_code == 201, r.text
    return r.json()["ref"]  # e.g. "@oa/gpt-4o"


@pytest.fixture
def providers(stack):
    """Two providers, each with one registered model, added through the real API."""
    client, *_ = stack
    oa_id = register_provider(client, "openai", "oa", "OA_KEY", stack[4])
    an_id = register_provider(client, "anthropic", "an", "AN_KEY", stack[5])
    gpt = add_model(client, oa_id, "gpt-4o")
    claude = add_model(client, an_id, "claude-sonnet-4-20250514")
    return {"oa_id": oa_id, "an_id": an_id, "gpt": gpt, "claude": claude}


# ---------------------------------------------------------------- registration
def test_register_providers_and_models_through_the_api(stack):
    client, ollama, oa, an, oa_url, an_url = stack
    oa_id = register_provider(client, "openai", "oa", "OA_KEY", oa_url)
    an_id = register_provider(client, "anthropic", "an", "AN_KEY", an_url)
    gpt = add_model(client, oa_id, "gpt-4o")
    claude = add_model(client, an_id, "claude-sonnet-4-20250514", reasoning=True)
    assert gpt == "@oa/gpt-4o" and claude == "@an/claude-sonnet-4-20250514"

    listed = client.get("/api/providers").json()
    assert {p["name"]: p["key_available"] for p in listed} == {"oa": True, "an": True}
    assert all(FAKE_KEY not in json.dumps(p) for p in listed)  # never returns the key

    models = {m["name"]: m for m in client.get("/api/models").json()}
    assert models[gpt]["available"] is True and models[gpt]["source"] == "cloud"
    assert models[claude]["reasoning"] is True
    assert "qwen3:8b" in models  # the local model is still listed alongside enterprise ones

    test_result = client.post(f"/api/providers/{oa_id}/test").json()
    assert test_result["status"] == "working"


# ---------------------------------------------------------------- mixed run + hosted judge + export
def test_mixed_run_with_hosted_single_judge_and_export(stack, providers):
    client, ollama, oa, an, *_ = stack
    gpt, claude = providers["gpt"], providers["claude"]

    r = client.post(
        "/api/runs",
        json={
            "models": ["qwen3:8b", gpt],
            "adhoc_cases": [CLS_CASE, GEN_CASE],
            "judge_mode": "single",
            "judge_model": claude,  # hosted judge, not itself a contestant
            "config": {"warmup": False},
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    done = wait_for(client, run_id, timeout=30)
    assert done["status"] == "completed", done.get("error")

    models_out = {m["name"]: m for m in done["models"]}
    assert models_out["qwen3:8b"]["source"] == "local" and models_out[gpt]["source"] == "cloud"
    assert models_out[gpt]["provider"] == "oa" and models_out[gpt]["model_versions"]

    results = client.get(f"/api/runs/{run_id}/results").json()["results"]
    by = {(x["model"], x["category"]): x for x in results}
    assert by[("qwen3:8b", "classification")]["primary"]["outcome"] == "correct"
    gpt_gen = by[(gpt, "generation")]
    assert gpt_gen["source"] == "cloud" and gpt_gen["provider"] == "oa"
    assert gpt_gen["primary"]["outcome"] == "judged" and gpt_gen["model_version"]

    summary = client.get(f"/api/runs/{run_id}/summary").json()
    rows = {row["model"]: row for row in summary["leaderboard"]}
    assert summary["mixed_sources"] is True
    assert claude not in rows  # the judge never appears as a contestant
    assert rows[gpt]["self_judged"] is False  # judge is a different model entirely

    # judging happened only after generation, and went only to the judge's provider
    judge_calls = [c for c in an.chat_requests() if "tool_choice" in (c["body"] or {})]
    assert len(judge_calls) == 2  # one per judged case (classification is auto-scored, not judged)
    assert oa.chat_requests()  # gpt-4o was still called for generation, but never as a judge
    assert not [c for c in oa.chat_requests() if "response_format" in (c["body"] or {})]

    csv_text = client.get(f"/api/runs/{run_id}/export?format=csv").text
    rows_csv = list(csv.DictReader(io.StringIO(csv_text)))
    gpt_csv = next(x for x in rows_csv if x["model"] == gpt and x["category"] == "generation")
    assert gpt_csv["source"] == "cloud" and gpt_csv["provider"] == "oa" and gpt_csv["model_version"]
    local_csv = next(x for x in rows_csv if x["model"] == "qwen3:8b")
    assert local_csv["source"] == "local" and local_csv["provider"] == ""
    assert FAKE_KEY not in csv_text

    exported = json.loads(client.get(f"/api/runs/{run_id}/export?format=json").text)
    assert exported["summary"]["mixed_sources"] is True
    json_row = next(x for x in exported["results"] if x["model"] == gpt and x["category"] == "generation")
    assert json_row["source"] == "cloud" and json_row["provider"] == "oa"
    assert FAKE_KEY not in json.dumps(exported)


# ---------------------------------------------------------------- cross-model judging across mixed models
def test_cross_model_judging_across_local_and_cloud(stack, providers):
    client, ollama, oa, an, *_ = stack
    gpt, claude = providers["gpt"], providers["claude"]

    r = client.post(
        "/api/runs",
        json={
            "models": ["qwen3:8b", "gemma:test", gpt, claude],
            "adhoc_cases": [GEN_CASE],
            "judge_mode": "cross_model",
            "config": {"warmup": False},
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    done = wait_for(client, run_id, timeout=30)
    assert done["status"] == "completed", done.get("error")

    results = client.get(f"/api/runs/{run_id}/results").json()["results"]
    by_model = {x["model"]: x for x in results}
    for author, res in by_model.items():
        judge_score = next(s for s in res["scores"] if s["kind"] == "judge")
        judged_by = {j["judge_model"] for j in judge_score["detail"]["judgements"]}
        assert author not in judged_by  # nobody judges their own answer
        assert judged_by == {"qwen3:8b", "gemma:test", gpt, claude} - {author}
        assert judge_score["detail"]["self_judged"] is False

    summary = client.get(f"/api/runs/{run_id}/summary").json()
    assert all(row["self_judged"] is False for row in summary["leaderboard"])
    assert summary["judging"]["mode"] == "cross_model"
    judges_seen = {j["model"] for j in summary["judging"]["judges"]}
    assert judges_seen == {"qwen3:8b", "gemma:test", gpt, claude}  # every model judged at least once


# ---------------------------------------------------------------- provider failure isolation
def test_authentication_failure_is_isolated_to_its_own_provider(stack, providers, monkeypatch):
    client, ollama, oa, an, *_ = stack
    gpt, claude = providers["gpt"], providers["claude"]
    monkeypatch.setenv("OA_KEY", "wrong-key-value")  # the fake OpenAI server will reject every request

    r = client.post(
        "/api/runs",
        json={
            "models": ["qwen3:8b", gpt, claude],
            "adhoc_cases": [CLS_CASE, CLS_CASE],
            "config": {"warmup": False},
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    done = wait_for(client, run_id, timeout=30)
    assert done["status"] == "completed"  # a provider failure never fails the whole run

    results = client.get(f"/api/runs/{run_id}/results").json()["results"]
    by_model: dict[str, list] = {}
    for x in results:
        by_model.setdefault(x["model"], []).append(x)

    assert all(r["status"] == "error" for r in by_model[gpt])
    assert any(
        "authentication failed" in (r["error"] or "").lower() or "incorrect" in (r["error"] or "").lower()
        for r in by_model[gpt]
    )
    assert len(oa.chat_requests()) == 1  # only the first request was attempted; the rest were short-circuited

    # the other provider and the local model are unaffected
    assert all(r["status"] == "ok" for r in by_model[claude])
    assert all(r["status"] == "ok" for r in by_model["qwen3:8b"])
    assert "wrong-key-value" not in json.dumps(results)


def test_registering_a_provider_with_no_data_sharing_acknowledgment_is_rejected(stack):
    client, *_ = stack
    r = client.post(
        "/api/providers",
        json={"kind": "openai", "name": "oa2", "key_env": "OA_KEY2", "acknowledge_data_sharing": False},
    )
    assert r.status_code == 422
    assert client.get("/api/providers").json() == []
