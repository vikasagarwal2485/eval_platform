"""10.2: select models -> run -> scoring -> summary -> export, over real HTTP against a fake Ollama."""

import csv
import dataclasses
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_ollama_server import running_fake_ollama
from tests.helpers import wait_for

CASES = [
    {
        "category": "classification",
        "title": "sentiment",
        "prompt": "Classify: I love it",
        "labels": ["positive", "negative"],
        "expected": "positive",
    },
    {
        "category": "reasoning",
        "title": "sum",
        "prompt": "What is 2+3?",
        "comparison": "numeric",
        "expected": "5",
    },
    {
        "category": "generation",
        "title": "haiku",
        "prompt": "Write a haiku about rain",
        "constraints": {"max_words": 30, "required_keywords": ["rain"]},
        "rubric": [{"name": "Imagery", "description": "vivid"}, {"name": "Form"}],
    },
]


@pytest.fixture
def stack(settings, file_session_factory):
    with running_fake_ollama() as (srv, url):
        s = dataclasses.replace(settings, ollama_base_url=url, request_timeout_s=20)
        with TestClient(create_app(s, session_factory=file_session_factory)) as client:  # real HttpOllamaClient
            yield srv, client


def test_full_flow_over_http(stack):
    srv, c = stack

    # 1. discovery through the real client
    health = c.get("/api/health").json()
    assert health["status"] == "ok" and health["ollama"]["version"] == "0.34.2"
    models = {m["name"]: m for m in c.get("/api/models").json()}
    assert set(models) == {"qwen3:8b", "gemma:test", "judge:test"} and models["qwen3:8b"]["thinking"] is True

    # 2. start a two-model run with a judge
    r = c.post(
        "/api/runs",
        json={"models": ["qwen3:8b", "gemma:test"], "adhoc_cases": CASES, "judge_model": "judge:test"},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    done = wait_for(c, run_id, timeout=30)
    assert done["status"] == "completed", done.get("error")
    assert done["progress"] == {"completed": 6, "total": 6} and done["ollama_version"] == "0.34.2"

    # 3. the wire protocol: grouped by model, warm-up + unload, judge last, thinking flag honoured
    order = [(b["model"], bool(b.get("messages")) and b["messages"][-1]["content"][:5]) for b in srv.requests]
    models_in_order = [m for m, _ in order]
    assert models_in_order[:1] == ["qwen3:8b"] and models_in_order.index("gemma:test") > models_in_order.index(
        "qwen3:8b"
    )
    assert models_in_order[-2:] == ["judge:test", "judge:test"] or models_in_order[-1] == "judge:test"
    assert any(b.get("keep_alive") == 0 and not b["messages"] for b in srv.requests)  # unload between models
    q_req = next(b for b in srv.requests if b["model"] == "qwen3:8b" and "2+3" in b["messages"][-1]["content"])
    assert q_req["think"] is True and q_req["options"]["temperature"] == 0 and q_req["options"]["seed"] == 42
    g_req = next(b for b in srv.requests if b["model"] == "gemma:test")
    assert "think" not in g_req  # non-thinking model: parameter omitted
    judge_req = next(b for b in srv.requests if b["model"] == "judge:test")
    assert judge_req["format"]["type"] == "object"  # structured output requested

    # 4. results and scoring
    results = c.get(f"/api/runs/{run_id}/results").json()["results"]
    by = {(x["model"], x["category"]): x for x in results}
    q_rea = by[("qwen3:8b", "reasoning")]
    assert q_rea["primary"] == {"value": 1.0, "outcome": "correct"}  # "<5>" from the REAL recorded stream
    assert q_rea["thinking"] and q_rea["output"].startswith("Final answer")  # reasoning trace separated
    assert q_rea["is_cold"] is True and q_rea["metrics"]["load_ms"] > 4000  # recorded 4.8 s load flagged cold
    assert q_rea["output_tokens"] == 182 and q_rea["tokens_per_s"] == pytest.approx(182 / 4.305027, rel=1e-3)
    assert by[("gemma:test", "reasoning")]["primary"]["outcome"] == "wrong"
    assert by[("qwen3:8b", "classification")]["primary"]["outcome"] == "correct"
    assert by[("gemma:test", "classification")]["primary"]["outcome"] == "wrong"
    gen = by[("gemma:test", "generation")]
    assert gen["primary"]["outcome"] == "judged" and gen["primary"]["value"] == pytest.approx(0.75)
    assert next(s for s in gen["scores"] if s["kind"] == "constraints")["outcome"] == "pass"

    # 5. summary / leaderboard
    s = c.get(f"/api/runs/{run_id}/summary").json()
    rows = {r["model"]: r for r in s["leaderboard"]}
    assert s["comparable"] and set(rows) == {"qwen3:8b", "gemma:test"}  # judge never appears as a contestant
    assert rows["qwen3:8b"]["composite"] == pytest.approx((1 + 1 + 0.75) / 3)
    assert rows["gemma:test"]["composite"] == pytest.approx((0 + 0 + 0.75) / 3)
    assert rows["qwen3:8b"]["performance"]["cold_requests"] == 1  # the recorded cold start
    assert rows["qwen3:8b"]["memory"] == {"size": 5_000_000_000, "size_vram": 5_000_000_000}
    assert rows["gemma:test"]["classification"]["accuracy"] == 0.0

    # 6. export
    text = c.get(f"/api/runs/{run_id}/export?format=csv").text
    rows_csv = list(csv.DictReader(io.StringIO(text)))
    assert len(rows_csv) == 6
    assert {r["outcome"] for r in rows_csv if r["model"] == "gemma:test"} == {"wrong", "judged"}
    exported = json.loads(c.get(f"/api/runs/{run_id}/export?format=json").text)
    assert exported["summary"]["leaderboard"][0]["model"] == "qwen3:8b" and len(exported["results"]) == 6

    # 7. re-run reproduces the configuration and links back
    again = c.post(f"/api/runs/{run_id}/rerun").json()
    assert again["parent_run_id"] == run_id and again["config"] == done["config"]
    wait_for(c, again["id"], timeout=30)
    cmp = c.get(f"/api/runs/compare?a={run_id}&b={again['id']}").json()
    assert {m["model"] for m in cmp["models"]} == {"qwen3:8b", "gemma:test"}
    assert all(m["composite"]["delta"] == pytest.approx(0) for m in cmp["models"])  # deterministic fake -> no change


def test_unreachable_ollama_over_real_connection(settings, file_session_factory):
    s = dataclasses.replace(settings, ollama_base_url="http://127.0.0.1:1")  # nothing listens here
    with TestClient(create_app(s, session_factory=file_session_factory)) as c:
        h = c.get("/api/health").json()
        assert h["status"] == "ollama_unreachable" and "127.0.0.1:1" in h["ollama"]["base_url"]
        m = c.get("/api/models")
        assert m.status_code == 503 and m.json()["detail"]["code"] == "ollama_unreachable"
        r = c.post("/api/runs", json={"models": ["a:1"], "adhoc_cases": CASES[:1]})
        assert r.status_code == 503


# ---------------------------------------------------------------- cross-model judging (6.1)
def test_cross_model_judging_end_to_end_over_http(stack):
    srv, c = stack
    srv.judge_scores = {"qwen3:8b": 4, "gemma:test": 2}  # qwen3 is the lenient judge (75%), gemma the strict one (25%)

    r = c.post(
        "/api/runs",
        json={
            "models": ["qwen3:8b", "gemma:test"],
            "adhoc_cases": CASES,
            "judge_mode": "cross_model",
            "config": {"judge_reasoning": True},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["judge_mode"] == "cross_model" and r.json()["judge_model"] is None
    run_id = r.json()["id"]
    done = wait_for(c, run_id, timeout=60)
    assert done["status"] == "completed", done.get("error")

    # -- on the wire: all generation first, then judging grouped judge by judge, unloading between judges
    log = [
        (b["model"], "unload" if not b.get("messages") else ("judge" if b.get("format") else "gen"))
        for b in srv.requests
    ]
    first_judge = next(i for i, (_, kind) in enumerate(log) if kind == "judge")
    assert all(kind != "judge" for _, kind in log[:first_judge])
    assert all(kind != "gen" for _, kind in log[first_judge:])
    judging = [(m, k) for m, k in log[first_judge:]]
    order = [m for m, k in judging if k == "judge"]
    assert [m for i, m in enumerate(order) if i == 0 or order[i - 1] != m] == ["qwen3:8b", "gemma:test"]
    assert judging.count(("qwen3:8b", "unload")) == 1  # the first judge is unloaded before the second loads
    judge_reqs = [b for b in srv.requests if b.get("format")]
    q_judge = next(b for b in judge_reqs if b["model"] == "qwen3:8b")
    g_judge = next(b for b in judge_reqs if b["model"] == "gemma:test")
    assert q_judge["think"] is False and "think" not in g_judge  # thinking off only for the thinking-capable judge
    # 1 generation + 1 reasoning-quality answer per model, each judged once by the other model
    assert len(judge_reqs) == 4

    # -- nobody judged themselves; every judge's score is visible
    results = c.get(f"/api/runs/{run_id}/results").json()["results"]
    by = {(x["model"], x["category"]): x for x in results}

    def judgements(model, category, kind):
        s = next(s for s in by[(model, category)]["scores"] if s["kind"] == kind)
        return s["detail"]

    q_gen = judgements("qwen3:8b", "generation", "judge")
    g_gen = judgements("gemma:test", "generation", "judge")
    assert [j["judge_model"] for j in q_gen["judgements"]] == ["gemma:test"]
    assert [j["judge_model"] for j in g_gen["judgements"]] == ["qwen3:8b"]
    assert q_gen["self_judged"] is False and g_gen["self_judged"] is False and q_gen["mode"] == "cross_model"
    assert by[("qwen3:8b", "generation")]["primary"]["value"] == pytest.approx(0.25)  # judged by strict gemma
    assert by[("gemma:test", "generation")]["primary"]["value"] == pytest.approx(0.75)  # judged by lenient qwen3
    assert q_gen["judgements"][0]["criteria"]["Imagery"]["reason"] == "scored by gemma:test"
    rq = judgements("qwen3:8b", "reasoning", "judge_reasoning")
    assert [j["judge_model"] for j in rq["judgements"]] == ["gemma:test"]  # reasoning quality: cross-judged too
    # correctness scoring and speed are untouched by judging
    assert by[("qwen3:8b", "reasoning")]["primary"]["outcome"] == "correct" and by[("qwen3:8b", "reasoning")]["is_cold"]

    # -- summary: mode, per-judge strictness, no self-judged anywhere, judges never appear as contestants
    s = c.get(f"/api/runs/{run_id}/summary").json()
    assert s["judging"]["mode"] == "cross_model" and s["attempt"]["judge_mode"] == "cross_model"
    means = {j["model"]: j["mean_score"] for j in s["judging"]["judges"]}
    assert means == {"qwen3:8b": pytest.approx(0.75), "gemma:test": pytest.approx(0.25)}
    assert all(row["self_judged"] is False and row["judges_per_answer"] == 1 for row in s["leaderboard"])
    assert {row["model"] for row in s["leaderboard"]} == {"qwen3:8b", "gemma:test"}

    # -- export carries the mode and each judge's score
    rows = list(csv.DictReader(io.StringIO(c.get(f"/api/runs/{run_id}/export?format=csv").text)))
    gen_rows = {r["model"]: r for r in rows if r["category"] == "generation"}
    assert {r["judge_mode"] for r in rows} == {"cross_model"}
    assert gen_rows["qwen3:8b"]["judges"] == "gemma:test=0.250" and gen_rows["gemma:test"]["judges"] == "qwen3:8b=0.750"
    exported = json.loads(c.get(f"/api/runs/{run_id}/export?format=json").text)
    assert exported["summary"]["judging"]["mode"] == "cross_model"
    assert any(r["judgements"] for r in exported["results"])

    # -- re-score the same outputs with a neutral single judge: both attempts stay readable
    before = {(x["model"], x["category"]): x["output"] for x in results}
    assert c.post(f"/api/runs/{run_id}/rescore", json={"judge_model": "judge:test"}).status_code == 202
    wait_for(c, run_id, timeout=60)
    s2 = c.get(f"/api/runs/{run_id}/summary").json()
    assert [a["judge_mode"] for a in s2["attempts"]] == ["cross_model", "single"]
    assert s2["attempt"]["judge_model"] == "judge:test"
    first = c.get(f"/api/runs/{run_id}/summary?attempt={s2['attempts'][0]['id']}").json()
    assert first["judging"]["mode"] == "cross_model"
    after = {(x["model"], x["category"]): x["output"] for x in c.get(f"/api/runs/{run_id}/results").json()["results"]}
    assert after == before  # outputs are never regenerated by re-scoring
