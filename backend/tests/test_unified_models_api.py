"""5.3: unified model list and provider status in health."""

from datetime import UTC, datetime

import pytest

from app import repo
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder, new_client


@pytest.fixture
def registry(file_session_factory):
    with file_session_factory() as s:
        oa = repo.create_provider(
            s, kind="openai", name="oa", key_env="OA_KEY", base_url=None, ack_at=datetime.now(UTC)
        )
        an = repo.create_provider(
            s, kind="anthropic", name="an", key_env="AN_KEY", base_url=None, ack_at=datetime.now(UTC)
        )
        repo.add_registered_model(s, oa.id, "gpt-4o", display_name="GPT-4o")
        repo.add_registered_model(s, oa.id, "o3", reasoning=True)
        repo.add_registered_model(s, oa.id, "off", enabled=False)
        repo.add_registered_model(s, an.id, "claude")
        s.commit()
    return file_session_factory


def client(settings, sf, ollama):
    return new_client(settings, sf, ollama)


def ollama(*names, **kw):
    return FakeOllama([make_tag(n, thinking=(n == "qwen3:8b")) for n in names], make_responder(), **kw)


def test_mixed_list_marks_source_provider_and_availability(settings, registry, monkeypatch):
    monkeypatch.setenv("OA_KEY", "k")
    monkeypatch.delenv("AN_KEY", raising=False)
    with client(settings, registry, ollama("qwen3:8b", "gemma:test")) as c:
        models = c.get("/api/models").json()
    # fully alphabetical now (add-provider-availability-gating) - not "locals first, then cloud" as before
    assert [m["name"] for m in models] == ["@an/claude", "@oa/gpt-4o", "@oa/o3", "gemma:test", "qwen3:8b"]
    by = {m["name"]: m for m in models}
    # neither is registered under any provider (add-ollama-model-registration-required), so both are listed
    # but disabled - registering one under an `ollama`-kind provider is covered in test_ollama_provider_kind.py
    assert (by["qwen3:8b"]["source"], by["qwen3:8b"]["provider"], by["qwen3:8b"]["available"]) == ("local", None, False)
    assert by["qwen3:8b"]["unavailable_reason"] and "not registered" in by["qwen3:8b"]["unavailable_reason"]
    gpt = by["@oa/gpt-4o"]
    assert (gpt["source"], gpt["provider"], gpt["provider_kind"], gpt["display_name"]) == (
        "cloud",
        "oa",
        "openai",
        "GPT-4o",
    )
    assert gpt["available"] is True and gpt["unavailable_reason"] is None and gpt["thinking"] is False
    assert (
        by["@oa/o3"]["thinking"] is True
        and by["@oa/o3"]["reasoning"] is True
        and "thinking" in by["@oa/o3"]["capabilities"]
    )
    assert by["@oa/o3"]["display_name"] == "o3"


def test_a_cloud_model_without_a_key_is_listed_unavailable_with_the_reason(settings, registry, monkeypatch):
    monkeypatch.delenv("OA_KEY", raising=False)
    monkeypatch.setenv("AN_KEY", "k")
    with client(settings, registry, ollama("qwen3:8b")) as c:
        by = {m["name"]: m for m in c.get("/api/models").json()}
    assert by["@oa/gpt-4o"]["available"] is False
    assert by["@oa/gpt-4o"]["unavailable_reason"] == "API key not set: environment variable OA_KEY is empty"
    # claude's key IS set and it's a registered cloud model, so it's available; the bare local name is not
    # registered under any provider, so it's listed but disabled regardless of its own key-free nature
    assert by["@an/claude"]["available"] is True and by["qwen3:8b"]["available"] is False


def test_disabled_models_are_not_offered(settings, registry, monkeypatch):
    monkeypatch.setenv("OA_KEY", "k")
    with client(settings, registry, ollama("qwen3:8b")) as c:
        names = [m["name"] for m in c.get("/api/models").json()]
    assert "@oa/off" not in names and "@oa/gpt-4o" in names


def test_enterprise_models_are_still_listed_when_ollama_is_down(settings, registry, monkeypatch):
    monkeypatch.setenv("OA_KEY", "k")
    monkeypatch.setenv("AN_KEY", "k")
    with client(settings, registry, ollama(down=True)) as c:
        r = c.get("/api/models")
        health = c.get("/api/health").json()
    assert r.status_code == 200
    assert [m["name"] for m in r.json()] == ["@an/claude", "@oa/gpt-4o", "@oa/o3"] and all(
        m["available"] for m in r.json()
    )
    assert health["status"] == "ollama_unreachable" and health["ollama"]["reachable"] is False


def test_ollama_down_with_nothing_registered_keeps_the_503(settings, file_session_factory):
    with client(settings, file_session_factory, ollama(down=True)) as c:
        r = c.get("/api/models")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ollama_unreachable"


def test_ollama_down_with_only_disabled_models_registered_is_still_a_503(settings, file_session_factory):
    with file_session_factory() as s:
        p = repo.create_provider(s, kind="openai", name="oa", key_env="K", base_url=None, ack_at=None)
        repo.add_registered_model(s, p.id, "m", enabled=False)
        s.commit()
    with client(settings, file_session_factory, ollama(down=True)) as c:
        assert c.get("/api/models").status_code == 503


def test_ollama_only_setup_with_nothing_registered_lists_the_model_but_disabled(settings, file_session_factory):
    """`add-ollama-model-registration-required`: a bare local model is still listed (not hidden) even with zero
    providers registered at all, but it's unselectable until it's registered under an `ollama`-kind provider -
    this is a deliberate change from the platform's original "no registration needed for local models" default,
    confirmed with the user given the scope."""
    with client(settings, file_session_factory, ollama("qwen3:8b")) as c:
        (m,) = c.get("/api/models").json()
    assert m["name"] == "qwen3:8b" and m["digest"] == "digest-qwen3:8b" and m["thinking"] is True
    assert (m["source"], m["provider"], m["provider_kind"], m["reasoning"]) == ("local", None, None, False)
    assert m["available"] is False
    assert "not registered" in m["unavailable_reason"]


def test_refresh_still_rereads_ollama_and_the_registry(settings, registry, monkeypatch):
    monkeypatch.setenv("OA_KEY", "k")
    fake = ollama("a:1")
    with client(settings, registry, fake) as c:
        assert "b:2" not in [m["name"] for m in c.get("/api/models").json()]
        fake._models.append(make_tag("b:2"))
        names = [m["name"] for m in c.get("/api/models?refresh=1").json()]
        assert "b:2" in names and "@oa/gpt-4o" in names
        pid = c.post(
            "/api/providers",
            json={"kind": "openai", "name": "new", "key_env": "NEW_KEY", "acknowledge_data_sharing": True},
        ).json()["id"]
        c.post(f"/api/providers/{pid}/models", json={"model_id": "fresh"})
        assert "@new/fresh" in [m["name"] for m in c.get("/api/models").json()]  # registry changes need no restart


def test_health_lists_providers_and_their_key_status_without_keys(settings, registry, monkeypatch):
    monkeypatch.setenv("OA_KEY", "super-secret-value-1")
    monkeypatch.delenv("AN_KEY", raising=False)
    with client(settings, registry, ollama("qwen3:8b")) as c:
        r = c.get("/api/health")
    h = r.json()
    assert h["status"] == "ok" and h["ollama"]["reachable"] is True
    assert h["providers"] == [
        {"name": "an", "kind": "anthropic", "key_env": "AN_KEY", "key_available": False},
        {"name": "oa", "kind": "openai", "key_env": "OA_KEY", "key_available": True},
    ]
    assert "super-secret-value-1" not in r.text


def test_health_without_providers_has_an_empty_list(settings, file_session_factory):
    with client(settings, file_session_factory, ollama("qwen3:8b")) as c:
        assert c.get("/api/health").json()["providers"] == []
