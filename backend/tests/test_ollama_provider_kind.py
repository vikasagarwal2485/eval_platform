"""`add-ollama-provider-kind`: registering a local Ollama server as a provider, through the same
`/api/providers` surface an enterprise provider uses - "Test connection", "Fetch models", and per-model
registration all work the same way, with no API key involved at all."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from app.schemas import EvalConfigIn
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder


def ollama_provider(client, **over):
    body = {"kind": "ollama", "name": "ollama-main", **over}
    return client.post("/api/providers", json=body)


@pytest.fixture
def transport():
    """Answers Ollama's REST surface (`/api/version`, `/api/tags`) the way `HttpOllamaClient` expects."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.1"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "digest": "d1"}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def client(settings, file_session_factory, transport):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=transport)
    ) as c:
        yield c


# ---------------------------------------------------------------- registration
def test_register_an_ollama_provider_needs_no_key_and_no_acknowledgment(client):
    r = ollama_provider(client)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kind"] == "ollama"
    assert p["key_env"] is None
    assert p["key_available"] is True  # nothing to be missing
    assert p["data_sharing_acknowledged_at"] is None  # never required, so never recorded either


def test_ollama_provider_can_set_its_own_server_url(client):
    r = ollama_provider(client, base_url="http://remote-ollama.example:11434")
    assert r.status_code == 201
    assert r.json()["base_url"] == "http://remote-ollama.example:11434"


def test_non_ollama_kind_still_requires_a_key_env(client):
    r = client.post("/api/providers", json={"kind": "openai", "name": "oa"})
    assert r.status_code == 422
    assert "key_env" in str(r.json())


# ---------------------------------------------------------------- test connection
def test_connection_pings_the_ollama_server(client):
    pid = ollama_provider(client).json()["id"]
    r = client.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200
    assert r.json()["status"] == "working"


def test_connection_reports_unreachable_not_key_not_set(settings, file_session_factory):
    unreachable = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    fake = FakeOllama([], make_responder())
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=unreachable)
    ) as c:
        pid = ollama_provider(c).json()["id"]
        r = c.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200
    assert r.json()["status"] == "unreachable"  # never "key_not_set" - there is no key to be missing


# ---------------------------------------------------------------- fetch + register models
def test_fetch_models_lists_whats_pulled_in_ollama(client):
    pid = ollama_provider(client).json()["id"]
    r = client.get(f"/api/providers/{pid}/available-models")
    assert r.status_code == 200
    assert r.json()["models"] == [{"id": "qwen3:8b", "already_added": False}]


def test_register_a_model_one_by_one_like_an_enterprise_provider(client):
    pid = ollama_provider(client).json()["id"]
    r = client.post(f"/api/providers/{pid}/models", json={"model_id": "qwen3:8b"})
    assert r.status_code == 201
    assert r.json()["ref"] == "@ollama-main/qwen3:8b"
    assert client.get(f"/api/providers/{pid}/available-models").json()["models"] == [
        {"id": "qwen3:8b", "already_added": True}
    ]


# ---------------------------------------------------------------- unified /api/models list
def test_registered_ollama_model_is_tagged_local_not_cloud(client):
    pid = ollama_provider(client).json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "qwen3:8b"})
    models = client.get("/api/models").json()
    entry = next(m for m in models if m["name"] == "@ollama-main/qwen3:8b")
    assert entry["source"] == "local"
    assert entry["available"] is True


def test_registering_a_model_suppresses_its_bare_duplicate(client):
    """`add-ollama-model-registration-required`: once `qwen3:8b` is registered as `@ollama-main/qwen3:8b`, the
    bare name no longer appears separately - there is exactly one entry for this model, not two."""
    names_before = {m["name"] for m in client.get("/api/models").json()}
    assert "qwen3:8b" in names_before  # unregistered, listed-but-disabled

    pid = ollama_provider(client).json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "qwen3:8b"})

    names_after = {m["name"] for m in client.get("/api/models").json()}
    assert "qwen3:8b" not in names_after
    assert "@ollama-main/qwen3:8b" in names_after


def test_registered_ollama_model_not_currently_pulled_is_unavailable(settings, file_session_factory, transport):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())  # only qwen3:8b is actually installed
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=transport)
    ) as c:
        pid = ollama_provider(c).json()["id"]
        c.post(f"/api/providers/{pid}/models", json={"model_id": "gemma4:e4b"})  # registered, but not pulled
        models = c.get("/api/models").json()
    entry = next(m for m in models if m["name"] == "@ollama-main/gemma4:e4b")
    assert entry["source"] == "local"
    assert entry["available"] is False
    assert "not currently pulled" in entry["unavailable_reason"]


# ---------------------------------------------------------------- no data-sharing ack needed anywhere downstream
def test_declaring_a_registered_ollama_model_for_an_agent_needs_no_provider_ack(client, file_session_factory):
    pid = ollama_provider(client).json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "qwen3:8b"})
    with file_session_factory() as session:
        agent, _ = repo.create_agent(
            session,
            name="bot",
            kind="chatbot",
            declared_models={"default": "@ollama-main/qwen3:8b"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    assert agent.declared_models == {"default": "@ollama-main/qwen3:8b"}
