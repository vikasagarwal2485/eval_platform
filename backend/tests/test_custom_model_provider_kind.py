"""`add-custom-model-provider-kind`: registering a directly-called, non-chat-completions HTTP service as a
provider, through the same `/api/providers` surface every other kind uses - but with no key, a health-check-
based "Test connection" instead of a chat ping, and never synced to the gateway."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder


def custom_provider(client, **over):
    body = {"kind": "custom", "name": "context-classifier", "base_url": "http://127.0.0.1:8765", **over}
    return client.post("/api/providers", json=body)


@pytest.fixture
def client(settings, file_session_factory):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with TestClient(create_app(settings, ollama=fake, session_factory=file_session_factory)) as c:
        yield c


# ---------------------------------------------------------------- registration
def test_register_a_custom_provider_needs_no_key_and_no_acknowledgment(client):
    r = custom_provider(client)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kind"] == "custom"
    assert p["key_env"] is None
    assert p["key_available"] is True  # nothing to be missing
    assert p["data_sharing_acknowledged_at"] is None  # never required, so never recorded either


def test_custom_provider_requires_a_base_url(client):
    r = client.post("/api/providers", json={"kind": "custom", "name": "ctx"})
    assert r.status_code == 422
    assert "base URL" in str(r.json())


def test_custom_provider_can_set_a_health_check_path(client):
    r = custom_provider(client, health_check_path="/healthz")
    assert r.status_code == 201
    assert r.json()["health_check_path"] == "/healthz"


def test_health_check_path_must_start_with_a_slash(client):
    r = custom_provider(client, health_check_path="healthz")
    assert r.status_code == 422
    assert "health-check path" in str(r.json())


# ---------------------------------------------------------------- availability
def test_a_custom_provider_with_no_key_is_available(client):
    pid = custom_provider(client).json()["id"]
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is True


# ---------------------------------------------------------------- never offered where a chat model is expected
def test_a_custom_kind_model_never_appears_in_the_unified_models_list(client):
    """`/api/models` backs Run Evaluation setup's model picker and every declared-model/evaluator picker
    (`add-custom-model-provider-kind`) - a custom-kind model cannot serve any of those roles, so it must never
    appear there at all, not even marked unavailable."""
    pid = custom_provider(client).json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "classify"})
    names = [m["name"] for m in client.get("/api/models").json()]
    assert "@context-classifier/classify" not in names


# ---------------------------------------------------------------- models
def test_register_a_model_under_a_custom_provider(client):
    pid = custom_provider(client).json()["id"]
    r = client.post(f"/api/providers/{pid}/models", json={"model_id": "classify"})
    assert r.status_code == 201
    assert r.json()["ref"] == "@context-classifier/classify"


def test_auto_discovery_is_not_offered_for_a_custom_provider(client):
    pid = custom_provider(client).json()["id"]
    r = client.get(f"/api/providers/{pid}/available-models")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_supported"


# ---------------------------------------------------------------- test connection (health check, not a chat call)
def test_custom_provider_health_check_succeeds(settings, file_session_factory):
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"status": "ok"}))
    fake = FakeOllama([], make_responder())
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=transport)
    ) as c:
        pid = custom_provider(c).json()["id"]
        r = c.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200 and r.json()["status"] == "working"


def test_custom_provider_health_check_fails_unreachable(settings, file_session_factory):
    unreachable = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    fake = FakeOllama([], make_responder())
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=unreachable)
    ) as c:
        pid = custom_provider(c).json()["id"]
        r = c.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200 and r.json()["status"] == "unreachable"


# ---------------------------------------------------------------- data-sharing acknowledgment exemption
def test_a_custom_kind_declared_model_needs_no_data_sharing_acknowledgment(file_session_factory):
    from app import repo
    from app.schemas import EvalConfigIn

    with file_session_factory() as session:
        repo.create_provider(
            session,
            kind="custom",
            name="context-classifier",
            key_env=None,
            base_url="http://127.0.0.1:8765",
            ack_at=None,
        )
        agent, _ = repo.create_agent(
            session,
            name="bot",
            kind="reasoning",
            declared_models={"classification": "@context-classifier/classify"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    assert agent.declared_models == {"classification": "@context-classifier/classify"}


def test_a_custom_kind_fallback_also_needs_no_acknowledgment(file_session_factory):
    from app import repo
    from app.schemas import EvalConfigIn

    with file_session_factory() as session:
        repo.create_provider(
            session,
            kind="custom",
            name="context-classifier",
            key_env=None,
            base_url="http://127.0.0.1:8765",
            ack_at=None,
        )
        agent, _ = repo.create_agent(
            session,
            name="bot",
            kind="reasoning",
            declared_models={"classification": {"model": "qwen3:8b", "fallback": "@context-classifier/classify"}},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    assert agent.declared_models["classification"]["fallback"] == "@context-classifier/classify"


def test_custom_provider_health_check_uses_configured_path(settings, file_session_factory):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200)

    fake = FakeOllama([], make_responder())
    with TestClient(
        create_app(
            settings, ollama=fake, session_factory=file_session_factory, provider_transport=httpx.MockTransport(handler)
        )
    ) as c:
        pid = custom_provider(c, health_check_path="/healthz").json()["id"]
        c.post(f"/api/providers/{pid}/test")
    assert seen == ["/healthz"]
