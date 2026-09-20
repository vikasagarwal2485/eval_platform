import csv
import io
import json

import pytest

from tests.fakes import FakeOllama, make_stream, make_tag
from tests.helpers import CLS, GEN, REA, make_responder, new_client, start_run, two_models, wait_for


def test_csv_export_columns_and_row_count(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder({"a:1": {"What is 2+3": "Final answer: 6"}}))
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS, REA, GEN], config={"warmup": False, "repeats": 2}, judge_model="b:1")
        wait_for(c, run["id"])
        r = c.get(f"/api/runs/{run['id']}/export?format=csv")
    assert (
        r.status_code == 200
        and "attachment" in r.headers["content-disposition"]
        and r.headers["content-type"].startswith("text/csv")
    )
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2 * 3 * 2  # models x cases x repeats
    for col in (
        "model",
        "category",
        "score",
        "outcome",
        "latency_ms",
        "tokens_per_s",
        "ttft_ms",
        "output_tokens",
        "repeat",
    ):
        assert col in rows[0]
    a_rea = [x for x in rows if x["model"] == "a:1" and x["category"] == "reasoning"]
    assert {x["outcome"] for x in a_rea} == {"wrong"} and {x["score"] for x in a_rea} == {"0.0"}
    assert a_rea[0]["expected"] == "5" and a_rea[0]["final_answer"] == "6"
    gen = [x for x in rows if x["category"] == "generation"]
    assert all(x["outcome"] == "judged" and float(x["score"]) == 0.75 and x["constraints"] == "pass" for x in gen)


def test_csv_quotes_multiline_output(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], lambda m, msgs, o: make_stream('line one,\n"quoted", line two'))
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [{"category": "generation", "prompt": "x"}], config={"warmup": False})
        wait_for(c, run["id"])
        text = c.get(f"/api/runs/{run['id']}/export?format=csv").text
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["output"] == 'line one,\n"quoted", line two' and row["outcome"] == "unscored" and row["score"] == ""


def test_json_export_has_run_summary_and_results(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], make_responder())) as c:
        run = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        wait_for(c, run["id"])
        r = c.get(f"/api/runs/{run['id']}/export?format=json")
        bad = c.get(f"/api/runs/{run['id']}/export?format=xml")
    d = json.loads(r.text)
    assert d["run"]["id"] == run["id"] and len(d["results"]) == 1 and d["summary"]["leaderboard"][0]["model"] == "a:1"
    assert bad.status_code == 422


def test_compare_two_runs_overlapping_and_disjoint_models(settings, file_session_factory):
    state = {"a_reasoning": "Final answer: 6"}

    def responder(model, messages, options):
        if model == "a:1" and "What is 2+3" in messages[-1]["content"]:
            return make_stream(state["a_reasoning"])
        return make_responder()(model, messages, options)

    fake = FakeOllama(two_models() + [make_tag("c:1")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        cfg = {"warmup": False}
        r1 = start_run(c, ["a:1", "b:1"], [CLS, REA], config=cfg)
        wait_for(c, r1["id"])
        state["a_reasoning"] = "Final answer: 5"  # "after" improvement for a:1
        r2 = start_run(c, ["a:1", "c:1"], [CLS, REA], config=cfg)
        wait_for(c, r2["id"])
        d = c.get(f"/api/runs/compare?a={r1['id']}&b={r2['id']}").json()
        bad_weights = c.get(f"/api/runs/compare?a={r1['id']}&b={r2['id']}&weights=zzz:1")
        missing = c.get(f"/api/runs/compare?a={r1['id']}&b=9999")
    assert [m["model"] for m in d["models"]] == ["a:1"]  # only the overlap
    assert d["only_in_a"] == ["b:1"] and d["only_in_b"] == ["c:1"]
    a = d["models"][0]
    assert a["same_digest"] is True
    assert a["categories"]["reasoning"] == {"a": 0.0, "b": 1.0, "delta": 1.0}
    assert a["categories"]["classification"]["delta"] == 0.0
    assert a["composite"]["delta"] == pytest.approx(0.5)
    assert set(a["performance"]) == {"latency_ms", "ttft_ms", "tokens_per_s"}
    reasoning = next(x for x in d["cases"] if x["category"] == "reasoning")
    assert (reasoning["model"], reasoning["a"], reasoning["b"], reasoning["delta"]) == ("a:1", 0.0, 1.0, 1.0)
    assert len(d["cases"]) == 2  # cases matched by category+prompt
    assert bad_weights.status_code == 422 and missing.status_code == 404


def test_compare_flags_changed_model_digest(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        r1 = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        wait_for(c, r1["id"])
        fake._models[0] = {**fake._models[0], "digest": "digest-NEW"}  # e.g. re-quantized / re-pulled
        r2 = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        wait_for(c, r2["id"])
        d = c.get(f"/api/runs/compare?a={r1['id']}&b={r2['id']}").json()
    assert d["models"][0]["same_digest"] is False
