"""5.1: provider registration API."""

import pytest

from app import repo
from app.repo import CaseSource
from app.schemas import CaseIn, ModelInfo
from tests.fakes import FakeOllama, make_tag
from tests.helpers import make_responder, new_client

SENTINEL = "sk-proj-SENTINEL0123456789abcdefXYZ"
BODY = {"kind": "openai", "name": "openai-main", "key_env": "OPENAI_API_KEY", "acknowledge_data_sharing": True}


@pytest.fixture
def client(settings, file_session_factory):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        yield c


def create(client, **over):
    return client.post("/api/providers", json={**BODY, **over})


def detail_text(r):
    return str(r.json().get("detail"))


# ---------------------------------------------------------------- registration
def test_register_a_provider(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = create(client)
    assert r.status_code == 201, r.text
    p = r.json()
    assert set(p) == {
        "id",
        "kind",
        "name",
        "key_env",
        "base_url",
        "key_available",
        "data_sharing_acknowledged_at",
        "created_at",
        "models",
    }
    assert (p["kind"], p["name"], p["key_env"], p["base_url"], p["models"]) == (
        "openai",
        "openai-main",
        "OPENAI_API_KEY",
        None,
        [],
    )
    assert p["key_available"] is False and p["data_sharing_acknowledged_at"]
    assert client.get("/api/providers").json()[0]["name"] == "openai-main"
    assert client.get(f"/api/providers/{p['id']}").json()["kind"] == "openai"


def test_key_availability_is_evaluated_live_on_every_read(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    pid = create(client).json()["id"]
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is False
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is True
    assert client.get("/api/providers").json()[0]["key_available"] is True
    monkeypatch.setenv("OPENAI_API_KEY", "  ")
    assert client.get(f"/api/providers/{pid}").json()["key_available"] is False


@pytest.mark.parametrize("name", ["", "Has-Upper", "has space", "@x", "-lead", "a/b", "n" * 41, "é"])
def test_invalid_names_are_rejected_without_registering(client, name):
    r = create(client, name=name)
    assert r.status_code == 422 and "name" in str(r.json())
    assert client.get("/api/providers").json() == []


def test_duplicate_name_is_a_conflict(client):
    assert create(client).status_code == 201
    r = create(client, key_env="OTHER_KEY")
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert len(client.get("/api/providers").json()) == 1


def test_unsupported_kind_is_rejected(client):
    assert create(client, kind="cohere").status_code == 422


@pytest.mark.parametrize(
    "value,fragment",
    [
        ("sk-proj-abc123def456", "looks like an API key"),
        ("sk-ant-api03-xyz", "looks like an API key"),
        ("lower_case", "upper-case"),
        ("", "must not be empty"),
        ("HAS SPACE", "looks like an API key"),
    ],
)
def test_a_key_or_bad_variable_name_is_refused_with_an_explanation(client, value, fragment):
    r = create(client, key_env=value)
    assert r.status_code == 422 and fragment in str(r.json())
    assert client.get("/api/providers").json() == []


def test_data_sharing_acknowledgment_is_required_and_recorded(client):
    r = create(client, acknowledge_data_sharing=False)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "acknowledgment_required"
    assert "prompts and model outputs" in r.json()["detail"]["message"] and "judge" in r.json()["detail"]["message"]
    body = {k: v for k, v in BODY.items() if k != "acknowledge_data_sharing"}
    assert client.post("/api/providers", json=body).status_code == 422
    assert client.get("/api/providers").json() == []
    ok = create(client)
    assert ok.json()["data_sharing_acknowledged_at"] is not None


@pytest.mark.parametrize("url", ["ftp://gw.example", "gw.example/v1", "http://", "javascript:alert(1)"])
def test_base_url_must_be_http_or_https(client, url):
    assert create(client, base_url=url).status_code == 422


def test_base_url_is_normalised_and_optional(client):
    assert create(client, base_url="https://gw.example/v1/").json()["base_url"] == "https://gw.example/v1"
    assert create(client, name="second", base_url="").json()["base_url"] is None


@pytest.mark.parametrize("field", ["api_key", "key", "secret", "token", "api_key_value"])
def test_there_is_no_field_that_accepts_a_key(client, field):
    r = create(client, **{field: SENTINEL})
    assert r.status_code == 422 and "Extra inputs are not permitted" in str(r.json())
    assert client.get("/api/providers").json() == []


# ---------------------------------------------------------------- nothing secret anywhere
def test_no_response_or_database_file_can_contain_a_key(client, monkeypatch, tmp_path, file_session_factory):
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    pid = create(client, base_url="https://gw.example/v1").json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    client.patch(f"/api/providers/{pid}", json={"key_env": "OPENAI_API_KEY"})
    texts = [
        client.get("/api/providers").text,
        client.get(f"/api/providers/{pid}").text,
        client.get("/api/models").text,
        client.get("/api/health").text,
    ]
    assert all(SENTINEL not in t for t in texts)
    engine = file_session_factory.kw["bind"]
    for suffix in ("", "-wal", "-shm"):
        path = engine.url.database + suffix
        try:
            data = open(path, "rb").read()
        except FileNotFoundError:
            continue
        assert SENTINEL.encode() not in data


# ---------------------------------------------------------------- update
def test_changing_the_variable_name_reevaluates_availability(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OTHER_KEY", SENTINEL)
    pid = create(client).json()["id"]
    r = client.patch(f"/api/providers/{pid}", json={"key_env": "OTHER_KEY"})
    assert r.status_code == 200 and r.json()["key_env"] == "OTHER_KEY" and r.json()["key_available"] is True
    assert r.json()["name"] == "openai-main"  # the name never changes: it is part of every model reference


def test_base_url_can_be_set_changed_and_cleared(client):
    pid = create(client).json()["id"]
    assert (
        client.patch(f"/api/providers/{pid}", json={"base_url": "https://a.example/"}).json()["base_url"]
        == "https://a.example"
    )
    assert (
        client.patch(f"/api/providers/{pid}", json={"key_env": "X_KEY"}).json()["base_url"] == "https://a.example"
    )  # untouched
    assert client.patch(f"/api/providers/{pid}", json={"base_url": ""}).json()["base_url"] is None


def test_update_rejects_bad_values_and_the_name_field(client):
    pid = create(client).json()["id"]
    assert client.patch(f"/api/providers/{pid}", json={"key_env": "sk-abc12345678"}).status_code == 422
    assert client.patch(f"/api/providers/{pid}", json={"base_url": "nope"}).status_code == 422
    assert client.patch(f"/api/providers/{pid}", json={"name": "renamed"}).status_code == 422
    assert client.patch("/api/providers/999", json={"key_env": "X"}).status_code == 404


# ---------------------------------------------------------------- delete
def test_delete_removes_the_provider_and_its_models(client):
    pid = create(client).json()["id"]
    client.post(f"/api/providers/{pid}/models", json={"model_id": "gpt-4o"})
    assert client.delete(f"/api/providers/{pid}").status_code == 204
    assert client.get("/api/providers").json() == [] and client.get(f"/api/providers/{pid}").status_code == 404
    assert client.delete(f"/api/providers/{pid}").status_code == 404


def running_run(sf, ref, status, judge=None):
    with sf() as s:
        snap = repo.get_or_create_snapshot(
            s, ModelInfo(name=ref, digest="", source="cloud", provider="openai-main", provider_kind="openai")
        )
        run = repo.create_run(
            s,
            name="r",
            config={},
            judge_model=judge,
            snapshots=[snap],
            cases=[CaseSource(CaseIn(category="generation", prompt="x"))],
        )
        repo.set_run_status(s, run.id, status)
        s.commit()
        return run.id


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_provider_used_by_an_active_run_cannot_be_deleted(client, file_session_factory, status):
    pid = create(client).json()["id"]
    running_run(file_session_factory, "@openai-main/gpt-4o", status)
    r = client.delete(f"/api/providers/{pid}")
    assert r.status_code == 409 and "queued or running" in r.json()["detail"]
    assert client.get(f"/api/providers/{pid}").status_code == 200


def test_deleting_after_the_run_finished_keeps_history_readable(client, file_session_factory):
    pid = create(client).json()["id"]
    run_id = running_run(file_session_factory, "@openai-main/gpt-4o", "completed")
    assert client.delete(f"/api/providers/{pid}").status_code == 204
    run = client.get(f"/api/runs/{run_id}").json()
    assert [m["name"] for m in run["models"]] == ["@openai-main/gpt-4o"]
