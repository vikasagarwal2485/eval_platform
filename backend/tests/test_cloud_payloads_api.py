"""5.4: source/provider/version, parameter records and attempts in run, results, summary and export payloads."""

import csv
import io
import json
from datetime import UTC, datetime

import pytest

from app import repo
from tests.fake_providers import FakeOpenAI, Step
from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS, make_responder, new_client, start_run, wait_for

KEY = "test-key-123"
GPT = "@oa/gpt-4o"


@pytest.fixture
def oa():
    srv = FakeOpenAI()
    url = srv.start()
    srv.answer = "positive"
    yield srv, url
    srv.stop()


@pytest.fixture
def env(file_session_factory, oa, monkeypatch):
    monkeypatch.setenv("OA_KEY", KEY)
    with file_session_factory() as s:
        p = repo.create_provider(
            s, kind="openai", name="oa", key_env="OA_KEY", base_url=oa[1], ack_at=datetime.now(UTC)
        )
        repo.add_registered_model(s, p.id, "gpt-4o")
        s.commit()
    return file_session_factory


@pytest.fixture
def mixed(settings, env, oa):
    """A completed run with a local and an enterprise model; the enterprise model was rate limited once."""
    oa[0].script.append(Step(kind="status", status=429, headers={"retry-after": "0"}))
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with new_client(settings, env, fake) as c:
        run = start_run(c, ["qwen3:8b", GPT], [CLS], config={"warmup": False, "seed": 7, "num_ctx": 4096})
        wait_for(c, run["id"])
        yield c, run["id"]


def test_run_detail_describes_each_models_source_provider_and_reported_version(mixed):
    c, rid = mixed
    models = {m["name"]: m for m in c.get(f"/api/runs/{rid}").json()["models"]}
    assert (models["qwen3:8b"]["source"], models["qwen3:8b"]["provider"], models["qwen3:8b"]["model_versions"]) == (
        "local",
        None,
        [],
    )
    cloud = models[GPT]
    assert (cloud["source"], cloud["provider"], cloud["provider_kind"]) == ("cloud", "oa", "openai")
    assert cloud["model_versions"] == ["gpt-4o-2024-08-06"] and cloud["digest"] == ""
    assert cloud["memory"] is None and cloud["size_bytes"] is None
    listed = {m["name"]: m for m in c.get("/api/runs").json()[0]["models"]}
    assert listed[GPT]["source"] == "cloud" and listed[GPT]["model_versions"] == []  # list view stays light


def test_results_carry_version_attempts_and_parameter_records(mixed):
    c, rid = mixed
    by = {r["model"]: r for r in c.get(f"/api/runs/{rid}/results").json()["results"]}
    cloud, local = by[GPT], by["qwen3:8b"]
    assert (cloud["source"], cloud["provider"], cloud["model_version"], cloud["attempts"]) == (
        "cloud",
        "oa",
        "gpt-4o-2024-08-06",
        2,
    )
    assert cloud["params_applied"]["seed"] == 7 and [i["name"] for i in cloud["params_ignored"]] == ["num_ctx"]
    assert cloud["metrics"]["retry_wait_ms"] >= 0 and cloud["is_cold"] is False
    assert (local["source"], local["provider"], local["model_version"], local["attempts"]) == ("local", None, None, 1)
    assert local["params_applied"] == {} and local["params_ignored"] == []


def test_summary_rows_and_the_mixed_flag(mixed):
    c, rid = mixed
    s = c.get(f"/api/runs/{rid}/summary").json()
    rows = {r["model"]: r for r in s["leaderboard"]}
    assert s["mixed_sources"] is True
    assert (rows[GPT]["source"], rows[GPT]["provider"], rows[GPT]["provider_kind"], rows[GPT]["model_versions"]) == (
        "cloud",
        "oa",
        "openai",
        ["gpt-4o-2024-08-06"],
    )
    assert (rows["qwen3:8b"]["source"], rows["qwen3:8b"]["provider"], rows["qwen3:8b"]["model_versions"]) == (
        "local",
        None,
        [],
    )
    assert rows[GPT]["memory"] is None
    assert rows[GPT]["performance"]["cold_requests"] == 0 and rows[GPT]["performance"]["warm_requests"] == 1


def test_csv_export_has_source_provider_version_and_ignored_parameters(mixed):
    c, rid = mixed
    r = c.get(f"/api/runs/{rid}/export?format=csv")
    rows = {x["model"]: x for x in csv.DictReader(io.StringIO(r.text))}
    for col in ("source", "provider", "model_version", "attempts", "params_ignored"):
        assert col in rows[GPT]
    assert (rows[GPT]["source"], rows[GPT]["provider"], rows[GPT]["model_version"], rows[GPT]["attempts"]) == (
        "cloud",
        "oa",
        "gpt-4o-2024-08-06",
        "2",
    )
    assert rows[GPT]["params_ignored"] == "num_ctx"
    assert (
        rows["qwen3:8b"]["source"],
        rows["qwen3:8b"]["provider"],
        rows["qwen3:8b"]["model_version"],
        rows["qwen3:8b"]["params_ignored"],
    ) == ("local", "", "", "")
    assert KEY not in r.text


def test_json_export_has_the_same_fields_and_details(mixed):
    c, rid = mixed
    r = c.get(f"/api/runs/{rid}/export?format=json")
    d = json.loads(r.text)
    row = next(x for x in d["results"] if x["model"] == GPT)
    assert (row["source"], row["provider"], row["model_version"]) == ("cloud", "oa", "gpt-4o-2024-08-06")
    assert (
        row["params_ignored_detail"][0]["name"] == "num_ctx"
        and "context size" in row["params_ignored_detail"][0]["reason"]
    )
    assert d["summary"]["mixed_sources"] is True and KEY not in r.text


def test_local_only_runs_read_as_local_with_no_provider(settings, env):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with new_client(settings, env, fake) as c:
        run = start_run(c, ["qwen3:8b"], [CLS], config={"warmup": False})
        wait_for(c, run["id"])
        rid = run["id"]
        s = c.get(f"/api/runs/{rid}/summary").json()
        (m,) = c.get(f"/api/runs/{rid}").json()["models"]
        (res,) = c.get(f"/api/runs/{rid}/results").json()["results"]
        rows = list(csv.DictReader(io.StringIO(c.get(f"/api/runs/{rid}/export?format=csv").text)))
    assert s["mixed_sources"] is False and s["leaderboard"][0]["source"] == "local"
    assert (m["source"], m["provider"], m["provider_kind"], m["model_versions"]) == ("local", None, None, [])
    assert (res["source"], res["provider"], res["model_version"]) == ("local", None, None)
    assert rows[0]["source"] == "local" and rows[0]["provider"] == "" and rows[0]["model_version"] == ""


def test_two_cloud_models_are_not_flagged_as_mixed(settings, env, oa):
    with env() as s:
        p = repo.get_provider_by_name(s, "oa")
        repo.add_registered_model(s, p.id, "o3")
        s.commit()
    fake = FakeOllama([], make_responder(), down=True)
    with new_client(settings, env, fake) as c:
        run = start_run(c, [GPT, "@oa/o3"], [CLS], config={"warmup": False})
        wait_for(c, run["id"])
        assert c.get(f"/api/runs/{run['id']}/summary").json()["mixed_sources"] is False
