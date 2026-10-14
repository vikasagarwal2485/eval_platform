"""5.2: end-to-end over the real HTTP API, with a fake Ollama and a fake Azure OpenAI resource.

Covers: registering an azure-openai provider (with and without its required fields), adding a
deployment, a generation run against it, Test Connection with and without a registered deployment,
the fetch-not-supported response, and a reasoning-flagged deployment with a configured
reasoning_effort. Needs no real key: the fake server checks a fake value set in the environment.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_ollama_server import running_fake_ollama
from tests.fake_providers import FakeAzureOpenAI
from tests.helpers import wait_for

FAKE_KEY = "test-key-123"  # matches FakeAzureOpenAI.expected_key

GEN_CASE = {
    "category": "generation",
    "title": "haiku",
    "prompt": "Write a haiku about rain",
    "rubric": [{"name": "Relevance"}, {"name": "Fluency"}],
}


@pytest.fixture
def stack(settings, file_session_factory, monkeypatch):
    """A real FastAPI app wired to a fake Ollama and a fake Azure OpenAI resource, all over real HTTP."""
    monkeypatch.setenv("AZ_KEY", FAKE_KEY)
    az = FakeAzureOpenAI()
    az_url = az.start()
    az.answer = "Rain taps the glass, soft and slow tonight"
    with running_fake_ollama() as (ollama, ollama_url):
        s = dataclasses.replace(settings, ollama_base_url=ollama_url, request_timeout_s=20)
        with TestClient(create_app(s, session_factory=file_session_factory)) as client:
            yield client, ollama, az, az_url
    az.stop()


def register_azure(client, az_url: str, *, api_version: str = "2024-12-01-preview") -> int:
    r = client.post(
        "/api/providers",
        json={
            "kind": "azure-openai",
            "name": "az",
            "key_env": "AZ_KEY",
            "base_url": az_url,
            "api_version": api_version,
            "acknowledge_data_sharing": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_deployment(client, provider_id: int, deployment: str, *, reasoning: bool = False, reasoning_effort=None) -> str:
    body = {"model_id": deployment, "reasoning": reasoning}
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    r = client.post(f"/api/providers/{provider_id}/models", json=body)
    assert r.status_code == 201, r.text
    return r.json()["ref"]


# ---------------------------------------------------------------- registration
def test_register_requires_base_url_and_api_version(stack):
    client, *_ = stack
    base = {"kind": "azure-openai", "name": "az", "key_env": "AZ_KEY", "acknowledge_data_sharing": True}
    assert client.post("/api/providers", json=base).status_code == 422
    assert client.post("/api/providers", json={**base, "base_url": "https://x.openai.azure.com"}).status_code == 422
    assert client.post("/api/providers", json={**base, "api_version": "2024-12-01-preview"}).status_code == 422
    assert client.get("/api/providers").json() == []


def test_register_and_add_a_deployment(stack):
    client, _, _, az_url = stack
    pid = register_azure(client, az_url)
    ref = add_deployment(client, pid, "o3-mini")
    assert ref == "@az/o3-mini"
    models = {m["name"]: m for m in client.get("/api/models").json()}
    assert models[ref]["available"] is True and models[ref]["source"] == "cloud"


# ---------------------------------------------------------------- test connection
def test_connection_before_and_after_a_deployment_exists(stack):
    client, _, az, az_url = stack
    pid = register_azure(client, az_url)
    before = client.post(f"/api/providers/{pid}/test").json()
    assert before["status"] == "no_deployments"
    assert az.requests == []  # never attempted a call with nothing to test

    add_deployment(client, pid, "o3-mini")
    after = client.post(f"/api/providers/{pid}/test").json()
    assert after["status"] == "working"
    rec = az.chat_requests()[0]
    assert rec["path"] == "/openai/deployments/o3-mini/chat/completions"
    assert rec["query"] == "api-version=2024-12-01-preview"


# ---------------------------------------------------------------- discovery
def test_discovery_is_not_offered(stack):
    client, *_, az_url = stack
    pid = register_azure(client, az_url)
    r = client.get(f"/api/providers/{pid}/available-models")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_supported"


# ---------------------------------------------------------------- generation run
def test_generation_run_against_a_deployment(stack):
    client, ollama, az, az_url = stack
    pid = register_azure(client, az_url)
    ref = add_deployment(client, pid, "my-gpt-4o")

    r = client.post(
        "/api/runs",
        json={"models": [ref], "adhoc_cases": [GEN_CASE], "config": {"warmup": False}},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    done = wait_for(client, run_id, timeout=30)
    assert done["status"] == "completed", done.get("error")

    results = client.get(f"/api/runs/{run_id}/results").json()["results"]
    assert len(results) == 1
    res = results[0]
    assert res["status"] == "ok" and res["source"] == "cloud" and res["provider"] == "az"
    assert res["output"].strip() and res["model_version"]
    rec = az.chat_requests()[0]
    assert rec["path"] == "/openai/deployments/my-gpt-4o/chat/completions"
    assert rec["headers"]["api-key"] == FAKE_KEY and "authorization" not in rec["headers"]


def test_reasoning_deployment_sends_reasoning_effort(stack):
    client, _, az, az_url = stack
    pid = register_azure(client, az_url)
    ref = add_deployment(client, pid, "o3-mini", reasoning=True, reasoning_effort="low")

    r = client.post(
        "/api/runs",
        json={"models": [ref], "adhoc_cases": [GEN_CASE], "config": {"warmup": False, "max_output_tokens": 256}},
    )
    assert r.status_code == 201, r.text
    done = wait_for(client, r.json()["id"], timeout=30)
    assert done["status"] == "completed", done.get("error")

    rec = az.chat_requests()[0]
    assert rec["body"]["reasoning_effort"] == "low"
    assert rec["body"]["max_completion_tokens"] == 256 and "max_tokens" not in rec["body"]

    results = client.get(f"/api/runs/{r.json()['id']}/results").json()["results"]
    assert results[0]["status"] == "ok"
