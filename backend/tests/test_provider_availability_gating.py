"""`add-provider-availability-gating`: "available" means the provider's key actually works, not just that the
env var holding it is non-empty - caught by reusing the last "Test connection" result rather than live-pinging
every provider on every page load."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_providers import FakeOpenAI
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder

KEY = "test-key-123"


@pytest.fixture
def server():
    oa = FakeOpenAI()
    url = oa.start()
    yield oa, url
    oa.stop()


@pytest.fixture
def client(settings, file_session_factory, server, monkeypatch):
    monkeypatch.setenv("OA_KEY", KEY)
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with TestClient(create_app(settings, ollama=fake, session_factory=file_session_factory)) as c:
        yield c


def provider(client, url, env="OA_KEY"):
    r = client.post(
        "/api/providers",
        json={
            "kind": "openai",
            "name": "oa",
            "key_env": env,
            "base_url": url,
            "acknowledge_data_sharing": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_never_tested_provider_with_a_present_key_is_available(client, server):
    _oa, url = server
    pid = provider(client, url)["id"]
    p = client.get(f"/api/providers/{pid}").json()
    assert p["key_available"] is True
    assert p["last_test_status"] is None and p["last_test_at"] is None


def test_a_failed_test_marks_the_provider_and_its_models_unavailable_everywhere(
    client, server, monkeypatch, file_session_factory
):
    _oa, url = server
    pid = provider(client, url)["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    # the key env var is present, but wrong - a static "is it set" check alone cannot catch this
    monkeypatch.setenv("OA_KEY", "wrong-key-value")

    test = client.post(f"/api/providers/{pid}/test")
    assert test.json()["status"] == "authentication_failed"

    p = client.get(f"/api/providers/{pid}").json()
    assert p["key_available"] is False
    assert p["last_test_status"] == "authentication_failed"
    assert "Check the value of OA_KEY" in p["unavailable_reason"]

    by = {m["name"]: m for m in client.get("/api/models").json()}
    assert by["@oa/gpt-4o"]["available"] is False
    assert "Check the value of OA_KEY" in by["@oa/gpt-4o"]["unavailable_reason"]


def test_retesting_successfully_clears_a_stale_failure(client, server, monkeypatch):
    _oa, url = server
    pid = provider(client, url)["id"]
    monkeypatch.setenv("OA_KEY", "wrong-key-value")
    client.post(f"/api/providers/{pid}/test")
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is False

    monkeypatch.setenv("OA_KEY", KEY)  # fix the key, then re-test
    retest = client.post(f"/api/providers/{pid}/test")
    assert retest.json()["status"] == "working"
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is True


def test_a_provider_whose_last_test_failed_cannot_start_a_run(client, server, monkeypatch):
    _oa, url = server
    pid = provider(client, url)["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    monkeypatch.setenv("OA_KEY", "wrong-key-value")
    client.post(f"/api/providers/{pid}/test")

    r = client.post(
        "/api/runs",
        json={"models": ["@oa/gpt-4o"], "adhoc_cases": [{"category": "generation", "prompt": "hi"}]},
    )
    assert r.status_code == 422
    assert "oa" in r.text.lower() or "api key" in r.text.lower()
