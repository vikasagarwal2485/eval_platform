from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama, make_tag


def client_for(settings, session_factory, fake):
    return TestClient(create_app(settings, ollama=fake, session_factory=session_factory))


def test_health_reports_config_and_reachable(settings, session_factory):
    with client_for(settings, session_factory, FakeOllama()) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ollama"]["reachable"] is True
    assert body["ollama"]["base_url"] == settings.ollama_base_url
    assert body["config"]["ollama_base_url"] == settings.ollama_base_url


def test_health_unreachable(settings, session_factory):
    with client_for(settings, session_factory, FakeOllama(down=True)) as c:
        body = c.get("/api/health").json()
    assert body["status"] == "ollama_unreachable"
    assert body["ollama"]["reachable"] is False
    assert settings.ollama_base_url in body["ollama"]["base_url"]
    assert body["ollama"]["error"]


def test_models_populated_with_thinking_flag(settings, session_factory):
    fake = FakeOllama([make_tag("qwen3:8b", thinking=True), make_tag("gemma3:4b")])
    with client_for(settings, session_factory, fake) as c:
        models = c.get("/api/models").json()
    assert [m["name"] for m in models] == ["gemma3:4b", "qwen3:8b"]
    q = models[1]
    assert q["thinking"] is True and q["quantization"] == "Q4_K_M" and q["parameter_size"] == "8B"
    assert q["digest"] and q["size_bytes"] and q["family"] == "qwen3"
    assert models[0]["thinking"] is False


def test_models_empty(settings, session_factory):
    with client_for(settings, session_factory, FakeOllama(models=[])) as c:
        assert c.get("/api/models").json() == []


def test_models_refresh_reflects_pull_and_remove(settings, session_factory):
    fake = FakeOllama([make_tag("a:1")])
    with client_for(settings, session_factory, fake) as c:
        assert [m["name"] for m in c.get("/api/models").json()] == ["a:1"]
        fake._models.append(make_tag("b:2"))
        assert [m["name"] for m in c.get("/api/models?refresh=1").json()] == ["a:1", "b:2"]
        fake._models.pop(0)
        assert [m["name"] for m in c.get("/api/models?refresh=1").json()] == ["b:2"]


def test_models_unreachable_returns_503(settings, session_factory):
    with client_for(settings, session_factory, FakeOllama(down=True)) as c:
        r = c.get("/api/models")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ollama_unreachable"
    assert r.json()["detail"]["base_url"] == settings.ollama_base_url


async def test_capabilities_fall_back_to_show_when_tags_lack_them():
    from app.core.model_discovery import ModelDiscovery

    tag = make_tag("old:1", thinking=True)
    tag_no_caps = {k: v for k, v in tag.items() if k != "capabilities"}
    fake = FakeOllama([tag_no_caps])
    fake._models = [tag_no_caps]

    async def show(name):
        return {"capabilities": ["completion", "thinking"]}

    fake.show = show
    models = await ModelDiscovery(fake).list_models()
    assert models[0].thinking is True
