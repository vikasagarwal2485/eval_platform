"""4.4: runs, re-runs and re-scores are validated against enterprise availability before anything is queued."""

from datetime import UTC, datetime

import pytest

from app import repo
from tests.fake_providers import FakeOpenAI
from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS, GEN, make_responder, new_client, start_run, wait_for

KEY = "test-key-123"
GPT, O3, OFF = "@oa/gpt-4o", "@oa/o3", "@oa/off"


@pytest.fixture
def oa():
    srv = FakeOpenAI()
    url = srv.start()
    srv.answer = "positive"
    yield srv, url
    srv.stop()


@pytest.fixture
def registered(file_session_factory, oa):
    """Provider `oa` (key variable OA_KEY) with enabled gpt-4o, o3 and a disabled model."""
    with file_session_factory() as s:
        p = repo.create_provider(
            s, kind="openai", name="oa", key_env="OA_KEY", base_url=oa[1], ack_at=datetime.now(UTC)
        )
        repo.add_registered_model(s, p.id, "gpt-4o")
        repo.add_registered_model(s, p.id, "o3", reasoning=True)
        repo.add_registered_model(s, p.id, "off", enabled=False)
        s.commit()
    return file_session_factory


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OA_KEY", KEY)


def client(settings, sf, ollama=None):
    fake = ollama or FakeOllama([make_tag("qwen3:8b")], make_responder())
    return new_client(settings, sf, fake), fake


def post(c, models, **kw):
    return c.post("/api/runs", json={"models": models, "adhoc_cases": [CLS], "config": {"warmup": False}, **kw})


def n_runs(c):
    return len(c.get("/api/runs").json())


# ---------------------------------------------------------------- refusals name every problem
def test_missing_key_is_refused_with_model_provider_and_variable(settings, registered, monkeypatch):
    monkeypatch.delenv("OA_KEY", raising=False)
    cm, _ = client(settings, registered)
    with cm as c:
        r = post(c, [GPT])
        assert r.status_code == 422
        d = r.json()["detail"]
        assert d["code"] == "model_unavailable" and d["models"] == [GPT]
        assert d["problems"] == [{"ref": GPT, "reason": "API key not set: environment variable OA_KEY is empty"}]
        assert GPT in d["message"] and "OA_KEY" in d["message"]
        assert n_runs(c) == 0


def test_disabled_unknown_and_unregistered_models_are_each_named(settings, registered, key):
    cm, _ = client(settings, registered)
    with cm as c:
        r = post(c, [OFF, "@ghost/x", "@oa/missing", "@bad"])
        by = {p["ref"]: p["reason"] for p in r.json()["detail"]["problems"]}
        assert by[OFF] == "model is disabled" and "provider 'ghost' is not registered" in by["@ghost/x"]
        assert "not registered under 'oa'" in by["@oa/missing"] and "not a valid model reference" in by["@bad"]
        assert n_runs(c) == 0


def test_the_judge_is_checked_before_any_generation_starts(settings, registered, monkeypatch):
    monkeypatch.delenv("OA_KEY", raising=False)
    cm, fake = client(settings, registered)
    with cm as c:
        r = post(c, ["qwen3:8b"], judge_model=GPT)
        assert r.status_code == 422 and r.json()["detail"]["problems"][0]["ref"] == GPT
        assert n_runs(c) == 0 and fake.calls == []  # nothing was generated


def test_mixed_local_and_enterprise_problems_are_reported_together(settings, registered, monkeypatch):
    monkeypatch.delenv("OA_KEY", raising=False)
    cm, _ = client(settings, registered)
    with cm as c:
        r = post(c, ["not-installed:1", GPT])
        d = r.json()["detail"]
        assert d["code"] == "model_unavailable" and {p["ref"] for p in d["problems"]} == {"not-installed:1", GPT}
        assert {p["reason"] for p in d["problems"]} >= {"not installed in Ollama"}


def test_legacy_local_only_errors_keep_their_shape(settings, registered, key):
    cm, _ = client(settings, registered)
    with cm as c:
        r = post(c, ["nope:1"])
        assert r.status_code == 422
        assert r.json()["detail"] == {
            "code": "model_not_installed",
            "message": "Not installed in Ollama: nope:1",
            "models": ["nope:1"],
        }


def test_ollama_down_still_returns_503_when_a_local_model_is_requested(settings, registered, key):
    cm, _ = client(settings, registered, FakeOllama(down=True))
    with cm as c:
        r = post(c, ["qwen3:8b", GPT])
        assert r.status_code == 503 and r.json()["detail"]["code"] == "ollama_unreachable"


# ---------------------------------------------------------------- what is allowed
def test_enterprise_only_run_starts_and_completes_while_ollama_is_down(settings, registered, key, oa):
    cm, _ = client(settings, registered, FakeOllama(down=True))
    with cm as c:
        r = post(c, [GPT])
        assert r.status_code == 201, r.text
        done = wait_for(c, r.json()["id"])
        assert done["status"] == "completed" and done["ollama_version"] is None
        res = c.get(f"/api/runs/{r.json()['id']}/results").json()["results"]
        assert res[0]["model"] == GPT and res[0]["status"] == "ok" and res[0]["primary"]["outcome"] == "correct"
    assert len(oa[0].chat_requests()) == 1


def test_local_and_enterprise_models_run_together_through_the_api(settings, registered, key, oa):
    cm, fake = client(settings, registered)
    with cm as c:
        r = post(c, ["qwen3:8b", GPT, O3])
        assert r.status_code == 201, r.text
        done = wait_for(c, r.json()["id"])
        by = {}
        for x in c.get(f"/api/runs/{done['id']}/results").json()["results"]:
            by.setdefault(x["model"], []).append(x)
    assert done["status"] == "completed" and set(by) == {"qwen3:8b", GPT, O3}
    assert by[GPT][0]["metrics"]["is_cloud"] is True and by["qwen3:8b"][0]["metrics"].get("is_cloud") is None
    assert [m["name"] for m in done["models"]] == ["qwen3:8b", GPT, O3]


def test_a_single_hosted_judge_over_local_models_is_not_a_contestant(settings, registered, key, oa):
    oa[0].judge_score = 4
    cm, _ = client(settings, registered)
    with cm as c:
        r = c.post(
            "/api/runs",
            json={"models": ["qwen3:8b"], "adhoc_cases": [GEN], "judge_model": GPT, "config": {"warmup": False}},
        )
        assert r.status_code == 201, r.text
        wait_for(c, r.json()["id"])
        s = c.get(f"/api/runs/{r.json()['id']}/summary").json()
    row = s["leaderboard"][0]
    assert row["self_judged"] is False and row["categories"]["generation"]["score"] == pytest.approx(0.75)
    assert [j["model"] for j in s["judging"]["judges"]] == [GPT]


# ---------------------------------------------------------------- re-run and re-score
def test_rerun_of_a_mixed_run_works_and_is_refused_when_the_key_disappears(settings, registered, monkeypatch, oa):
    monkeypatch.setenv("OA_KEY", KEY)
    cm, _ = client(settings, registered)
    with cm as c:
        run = start_run(c, ["qwen3:8b", GPT], [CLS], config={"warmup": False})
        wait_for(c, run["id"])
        again = c.post(f"/api/runs/{run['id']}/rerun")
        assert again.status_code == 201 and [m["name"] for m in again.json()["models"]] == ["qwen3:8b", GPT]
        wait_for(c, again.json()["id"])
        monkeypatch.delenv("OA_KEY")
        refused = c.post(f"/api/runs/{run['id']}/rerun")
        assert refused.status_code == 409 and GPT in refused.json()["detail"] and "OA_KEY" in refused.json()["detail"]


def test_rescore_checks_an_enterprise_single_judge_and_cross_model_enterprise_models(
    settings, registered, monkeypatch, oa
):
    monkeypatch.setenv("OA_KEY", KEY)
    cm, _ = client(settings, registered)
    with cm as c:
        run = start_run(c, ["qwen3:8b", GPT], [GEN], config={"warmup": False}, judge_mode="cross_model")
        wait_for(c, run["id"])
        monkeypatch.delenv("OA_KEY")
        single = c.post(f"/api/runs/{run['id']}/rescore", json={"judge_model": GPT})
        cross = c.post(f"/api/runs/{run['id']}/rescore", json={"judge_mode": "cross_model"})
        for r in (single, cross):
            assert r.status_code == 422 and r.json()["detail"]["code"] == "model_unavailable"
            assert r.json()["detail"]["problems"][0]["ref"] == GPT
        monkeypatch.setenv("OA_KEY", KEY)
        assert c.post(f"/api/runs/{run['id']}/rescore", json={"judge_mode": "cross_model"}).status_code == 202
        wait_for(c, run["id"])


def test_cross_model_rescore_of_local_models_that_disappeared_is_still_allowed(settings, file_session_factory):
    """Unchanged behaviour: missing local judges become error judgements, not a refusal."""
    fake = FakeOllama([make_tag("a:1"), make_tag("b:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [GEN], config={"warmup": False}, judge_mode="cross_model")
        wait_for(c, run["id"])
        fake._models.clear()
        assert c.post(f"/api/runs/{run['id']}/rescore", json={"judge_mode": "cross_model"}).status_code == 202
        wait_for(c, run["id"])
