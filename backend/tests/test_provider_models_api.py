"""5.2: provider model management, connection tests and model discovery."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_providers import FakeAnthropic, FakeOpenAI
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder

KEY = "test-key-123"


@pytest.fixture
def servers():
    oa, an = FakeOpenAI(), FakeAnthropic()
    urls = (oa.start(), an.start())
    yield oa, an, urls
    oa.stop()
    an.stop()


@pytest.fixture
def client(settings, file_session_factory, servers, monkeypatch):
    monkeypatch.setenv("OA_KEY", KEY)
    monkeypatch.setenv("AN_KEY", KEY)
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with TestClient(create_app(settings, ollama=fake, session_factory=file_session_factory)) as c:
        yield c


def provider(client, kind="openai", name="oa", env="OA_KEY", url=None):
    r = client.post(
        "/api/providers",
        json={"kind": kind, "name": name, "key_env": env, "base_url": url, "acknowledge_data_sharing": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- models
def test_add_a_model_by_id(client):
    pid = provider(client)["id"]
    r = client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    assert r.status_code == 201
    m = r.json()
    assert (m["model_id"], m["ref"], m["display_name"], m["enabled"], m["reasoning"]) == (
        "gpt-4o",
        "@oa/gpt-4o",
        "gpt-4o",
        True,
        False,
    )
    got = client.get(f"/api/providers/{pid}").json()["models"]
    assert [x["ref"] for x in got] == ["@oa/gpt-4o"]


def test_flags_and_gateway_style_ids(client):
    pid = provider(client)["id"]
    m = client.post(
        f"/api/providers/{pid}/models",
        json={"model_id": "openai/o3:high", "display_name": "O3 (high)", "reasoning": True, "enabled": False},
    ).json()
    assert (
        m["ref"] == "@oa/openai/o3:high"
        and m["display_name"] == "O3 (high)"
        and m["reasoning"] is True
        and m["enabled"] is False
    )


def test_duplicate_and_invalid_ids_are_rejected(client):
    pid = provider(client)["id"]
    assert client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"}).status_code == 201
    dup = client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    assert dup.status_code == 409 and "already registered" in dup.json()["detail"]
    for bad in ("", " gpt-4o", "gpt-4o ", "x" * 201):
        assert client.post(f"/api/providers/{pid}/models", json={"model_id": bad}).status_code == 422, repr(bad)
    assert client.post(f"/api/providers/{pid}/models", json={"model_id": "ok", "api_key": KEY}).status_code == 422
    assert client.post("/api/providers/999/models", json={"model_id": "x"}).status_code == 404
    assert len(client.get(f"/api/providers/{pid}").json()["models"]) == 1


def test_same_id_under_two_providers_is_fine(client):
    a, b = provider(client)["id"], provider(client, "anthropic", "an", "AN_KEY")["id"]
    assert client.post(f"/api/providers/{a}/models", json={"model_id": "m"}).status_code == 201
    assert client.post(f"/api/providers/{b}/models", json={"model_id": "m"}).status_code == 201


def test_enable_disable_reasoning_and_display_name(client):
    pid = provider(client)["id"]
    mid = client.post(f"/api/providers/{pid}/models", json={"model_id": "o3"}).json()["id"]
    r = client.patch(
        f"/api/providers/{pid}/models/{mid}", json={"enabled": False, "reasoning": True, "display_name": "O3"}
    )
    assert r.status_code == 200 and (r.json()["enabled"], r.json()["reasoning"], r.json()["display_name"]) == (
        False,
        True,
        "O3",
    )
    r = client.patch(f"/api/providers/{pid}/models/{mid}", json={"enabled": True})
    assert r.json()["enabled"] is True and r.json()["reasoning"] is True  # other fields untouched
    assert client.patch(f"/api/providers/{pid}/models/{mid}", json={"model_id": "renamed"}).status_code == 422


def test_remove_a_model_and_ownership_is_enforced(client):
    a, b = provider(client)["id"], provider(client, "anthropic", "an", "AN_KEY")["id"]
    m1 = client.post(f"/api/providers/{a}/models", json={"model_id": "m1"}).json()["id"]
    m2 = client.post(f"/api/providers/{a}/models", json={"model_id": "m2"}).json()["id"]
    assert client.delete(f"/api/providers/{b}/models/{m1}").status_code == 404  # wrong provider
    assert client.patch(f"/api/providers/{b}/models/{m1}", json={"enabled": False}).status_code == 404
    assert client.delete(f"/api/providers/{a}/models/{m1}").status_code == 204
    assert [m["id"] for m in client.get(f"/api/providers/{a}").json()["models"]] == [m2]
    assert client.delete(f"/api/providers/{a}/models/{m1}").status_code == 404


# ---------------------------------------------------------------- connection test
@pytest.mark.parametrize("kind,idx,env", [("openai", 0, "OA_KEY"), ("anthropic", 1, "AN_KEY")])
def test_working_connection(client, servers, kind, idx, env):
    pid = provider(client, kind, "p", env, servers[2][idx])["id"]
    r = client.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200 and r.json()["status"] == "working" and r.json()["base_url"] == servers[2][idx]
    assert KEY not in r.text


def test_key_not_set_never_calls_the_provider(client, servers, monkeypatch):
    monkeypatch.delenv("OA_KEY")
    pid = provider(client, url=servers[2][0])["id"]
    r = client.post(f"/api/providers/{pid}/test").json()
    assert r["status"] == "key_not_set" and "OA_KEY" in r["message"] and "restart" in r["message"]
    assert servers[0].requests == []


def test_authentication_failure_is_reported_without_echoing_the_key(client, servers, monkeypatch):
    monkeypatch.setenv("OA_KEY", "wrong-key-value")
    pid = provider(client, url=servers[2][0])["id"]
    r = client.post(f"/api/providers/{pid}/test").json()
    assert r["status"] == "authentication_failed" and "Check the value of OA_KEY" in r["message"]
    assert "wrong-key-value" not in str(r)


def test_unreachable_provider_shows_the_base_url(client):
    pid = provider(client, url="http://127.0.0.1:1")["id"]
    r = client.post(f"/api/providers/{pid}/test").json()
    assert r["status"] == "unreachable" and r["base_url"] == "http://127.0.0.1:1" and "gave up" in r["message"]


def test_rate_limited_connection_test(client, servers):
    pid = provider(client, url=servers[2][0])["id"]
    transport = httpx.MockTransport(lambda req: httpx.Response(429, json={"error": {"message": "slow down"}}))
    from app.providers.factories import make_factories

    client.app.state.router.factories = make_factories(client.app.state.settings, transport)
    client.app.state.router._backends.clear()
    r = client.post(f"/api/providers/{pid}/test").json()
    assert r["status"] == "rate_limited" and "slow down" in r["message"]


def test_unknown_provider_is_404(client):
    assert client.post("/api/providers/999/test").status_code == 404
    assert client.get("/api/providers/999/available-models").status_code == 404


# ---------------------------------------------------------------- discovery
def test_lists_the_providers_models_and_marks_registered_ones(client, servers):
    pid = provider(client, url=servers[2][0])["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o-mini"})
    r = client.get(f"/api/providers/{pid}/available-models")
    assert r.status_code == 200
    assert r.json()["models"] == [
        {"id": "gpt-4o", "already_added": False},
        {"id": "gpt-4o-mini", "already_added": True},
        {"id": "o3", "already_added": False},
    ]


def test_anthropic_discovery(client, servers):
    pid = provider(client, "anthropic", "an", "AN_KEY", servers[2][1])["id"]
    ids = [m["id"] for m in client.get(f"/api/providers/{pid}/available-models").json()["models"]]
    assert ids == ["claude-3-5-haiku-20241022", "claude-sonnet-4-20250514"]


def test_fetch_and_add_workflow(client, servers):
    pid = provider(client, url=servers[2][0])["id"]
    for mid in ("gpt-4o", "o3"):
        assert client.post(f"/api/providers/{pid}/models", json={"model_id": mid}).status_code == 201
    listing = client.get(f"/api/providers/{pid}/available-models").json()["models"]
    assert [m["already_added"] for m in listing] == [True, False, True]


def test_fetch_without_a_key_is_an_actionable_conflict(client, servers, monkeypatch):
    monkeypatch.delenv("OA_KEY")
    pid = provider(client, url=servers[2][0])["id"]
    r = client.get(f"/api/providers/{pid}/available-models")
    assert (
        r.status_code == 409
        and r.json()["detail"]["code"] == "key_not_set"
        and "OA_KEY" in r.json()["detail"]["message"]
    )


@pytest.mark.parametrize(
    "setup,code",
    [("bad_key", "authentication_failed"), ("unreachable", "unreachable")],
)
def test_failed_fetch_is_actionable_and_never_blocks_adding_by_id(client, servers, monkeypatch, setup, code):
    if setup == "bad_key":
        monkeypatch.setenv("OA_KEY", "wrong-key-value")
        pid = provider(client, url=servers[2][0])["id"]
    else:
        pid = provider(client, url="http://127.0.0.1:1")["id"]
    r = client.get(f"/api/providers/{pid}/available-models")
    assert r.status_code == 502 and r.json()["detail"]["code"] == code and "wrong-key-value" not in r.text
    added = client.post(f"/api/providers/{pid}/models", json={"model_id": "typed-by-hand"})
    assert added.status_code == 201  # typing an id still works


def test_provider_errors_echoing_the_key_are_redacted_in_responses(settings, file_session_factory, monkeypatch):
    secret = "sk-proj-Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"
    monkeypatch.setenv("OA_KEY", secret)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {secret}"}})
    )
    fake = FakeOllama([], make_responder())
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, provider_transport=transport)
    ) as c:
        pid = provider(c, url="http://gw.test")["id"]
        listing = c.get(f"/api/providers/{pid}/available-models")
        test = c.post(f"/api/providers/{pid}/test")
    for r in (listing, test):
        assert secret not in r.text and "[REDACTED]" in r.text


def test_servers_are_only_asked_for_models_not_chat(client, servers):
    pid = provider(client, url=servers[2][0])["id"]
    client.post(f"/api/providers/{pid}/test")
    client.get(f"/api/providers/{pid}/available-models")
    assert {r["path"] for r in servers[0].requests} == {"/v1/models"}  # no billable chat request for testing or listing
