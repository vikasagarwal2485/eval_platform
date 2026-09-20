"""4.1-4.3: summary, results, export and compare for cross-judged runs."""

import csv
import io
import json

import pytest

from tests.fakes import FakeOllama
from tests.helpers import CLS, GEN, make_responder, new_client, start_run, wait_for
from tests.test_cross_judging import gen_result, make_cross_responder, run_cross, tags


def cross_run(c, models=("a:1", "b:1"), cases=(CLS, GEN), **kw):
    rid, _ = run_cross(c, models, cases=cases, **kw)
    return rid


# ---------------------------------------------------------------- 4.1 summary
def test_summary_reports_mode_per_judge_stats_and_no_self_judging(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid = cross_run(c)
        s = c.get(f"/api/runs/{rid}/summary").json()
    assert s["attempt"]["judge_mode"] == "cross_model" and s["attempts"][0]["judge_mode"] == "cross_model"
    assert s["judging"]["mode"] == "cross_model"
    judges = {j["model"]: j for j in s["judging"]["judges"]}
    # a:1 gave 0.75 to b's answer, b:1 gave 0.25 to a's answer: a is the more lenient judge
    assert judges["a:1"] == {
        "model": "a:1",
        "judged": 1,
        "errors": 0,
        "mean_score": pytest.approx(0.75),
        "reasoning_mean_score": None,
    }
    assert judges["b:1"]["mean_score"] == pytest.approx(0.25)
    for row in s["leaderboard"]:
        assert row["self_judged"] is False and row["judges_per_answer"] == 1
    gen = {r["model"]: r["categories"]["generation"]["score"] for r in s["leaderboard"]}
    assert gen == {"a:1": pytest.approx(0.25), "b:1": pytest.approx(0.75)}


def test_summary_counts_judge_errors_and_judges_per_answer(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder(garbage={"a:1"}))
    with new_client(settings, file_session_factory, fake) as c:
        rid = cross_run(c, ("a:1", "b:1", "c:1"), cases=(GEN,))
        s = c.get(f"/api/runs/{rid}/summary").json()
    judges = {j["model"]: j for j in s["judging"]["judges"]}
    assert judges["a:1"]["errors"] == 2 and judges["a:1"]["judged"] == 0 and judges["a:1"]["mean_score"] is None
    assert judges["b:1"]["errors"] == 0 and judges["c:1"]["judged"] == 2
    assert all(r["judges_per_answer"] == 2 for r in s["leaderboard"])


def test_single_judge_with_a_contestant_still_reports_self_judged(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [GEN], judge_model="a:1", config={"warmup": False})
        wait_for(c, run["id"])
        s = c.get(f"/api/runs/{run['id']}/summary").json()
    rows = {r["model"]: r for r in s["leaderboard"]}
    assert rows["a:1"]["self_judged"] is True and rows["b:1"]["self_judged"] is False
    assert s["attempt"]["judge_mode"] == "single" and s["judging"]["mode"] == "single"
    assert [j["model"] for j in s["judging"]["judges"]] == ["a:1"]


def test_run_without_a_judge_reports_mode_none(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(tags("a:1"), make_responder())) as c:
        run = start_run(c, ["a:1"], [GEN], config={"warmup": False})
        wait_for(c, run["id"])
        s = c.get(f"/api/runs/{run['id']}/summary").json()
    assert s["judging"] == {"mode": "none", "judges": []} and s["attempt"]["judge_mode"] == "none"


# ---------------------------------------------------------------- 4.2 results and export
def test_results_expose_every_judges_score_criteria_and_reasons(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid = cross_run(c, ("a:1", "b:1", "c:1"), cases=(GEN,))
        r = gen_result(c, rid, "a:1")
    js = next(s for s in r["scores"] if s["kind"] == "judge")["detail"]["judgements"]
    assert {j["judge_model"] for j in js} == {"b:1", "c:1"}
    b = next(j for j in js if j["judge_model"] == "b:1")
    assert b["value"] == pytest.approx(0.25) and b["criteria"]["Fluency"] == {"score": 2, "reason": "scored by b:1"}


def test_csv_and_json_export_include_mode_and_per_judge_scores(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder(garbage={"c:1"}))
    with new_client(settings, file_session_factory, fake) as c:
        rid = cross_run(c, ("a:1", "b:1", "c:1"), cases=(CLS, GEN))
        text = c.get(f"/api/runs/{rid}/export?format=csv").text
        exported = json.loads(c.get(f"/api/runs/{rid}/export?format=json").text)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert "judge_mode" in rows[0] and "judges" in rows[0] and {r["judge_mode"] for r in rows} == {"cross_model"}
    a_gen = next(r for r in rows if r["model"] == "a:1" and r["category"] == "generation")
    assert set(a_gen["judges"].split(";")) == {"b:1=0.250", "c:1=error"}  # a's answer: judged by b, c failed
    assert next(r for r in rows if r["category"] == "classification")["judges"] == ""
    b_gen = next(r for r in exported["results"] if r["model"] == "b:1" and r["category"] == "generation")
    assert {j["judge_model"]: j["outcome"] for j in b_gen["judgements"]} == {"a:1": "judged", "c:1": "error"}
    assert exported["summary"]["judging"]["mode"] == "cross_model"


# ---------------------------------------------------------------- 4.3 composite and compare unchanged
def test_composite_and_categories_work_on_cross_judged_runs(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid = cross_run(c)
        rows = {r["model"]: r for r in c.get(f"/api/runs/{rid}/summary").json()["leaderboard"]}
        w = c.get(f"/api/runs/{rid}/summary?weights=classification:1,generation:3").json()["leaderboard"]
    assert rows["a:1"]["composite"] == pytest.approx((1.0 + 0.25) / 2)
    assert rows["b:1"]["composite"] == pytest.approx((1.0 + 0.75) / 2)
    assert {r["model"]: r["composite"] for r in w}["a:1"] == pytest.approx((1.0 * 1 + 0.25 * 3) / 4)


def test_compare_cross_judged_run_with_single_judge_run_flags_the_mode_difference(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "j:1"), make_cross_responder(scores={**{"a:1": 4, "b:1": 2}, "j:1": 3}))
    with new_client(settings, file_session_factory, fake) as c:
        cross = cross_run(c, cases=(GEN,))
        single = start_run(c, ["a:1", "b:1"], [GEN], judge_model="j:1", config={"warmup": False})
        wait_for(c, single["id"])
        d = c.get(f"/api/runs/compare?a={cross}&b={single['id']}").json()
        same = c.get(f"/api/runs/compare?a={cross}&b={cross}").json()
    assert d["judging"] == {"a": "cross_model", "b": "single", "same": False}
    assert same["judging"]["same"] is True
    a = next(m for m in d["models"] if m["model"] == "a:1")
    assert a["categories"]["generation"]["a"] == pytest.approx(0.25) and a["categories"]["generation"][
        "b"
    ] == pytest.approx(0.5)
    assert a["categories"]["generation"]["delta"] == pytest.approx(0.25)
