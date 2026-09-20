"""3.2-3.5: cross-model judging execution, ordering, cancellation and failure handling."""

import json
import re
import time

import pytest

from app.ollama.client import OllamaUnreachable
from tests.fakes import FakeOllama, make_stream, make_tag
from tests.helpers import CLS, GEN, REA, make_responder, new_client, start_run, wait_for

JUDGE_SCORE = {"a:1": 4, "b:1": 2, "c:1": 5}  # -> normalized 0.75, 0.25, 1.0


def is_judge_request(messages):
    return bool(messages) and messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]


def make_cross_responder(garbage=(), unreachable=(), scores=JUDGE_SCORE):
    base = make_responder()

    def responder(model, messages, options):
        if is_judge_request(messages):
            if model in unreachable:
                raise OllamaUnreachable("connection lost")
            if model in garbage:
                return make_stream("this is not json")
            crit = re.search(r"CRITERIA:\n(.*?)\n\nReturn JSON", messages[1]["content"], re.S).group(1)
            names = [ln[2:].split(":")[0] for ln in crit.splitlines() if ln.startswith("- ")]
            body = {n: {"score": scores[model], "reason": f"scored by {model}"} for n in names}
            return make_stream(json.dumps({"scores": body}))
        return base(model, messages, options)

    return responder


def tags(*names, thinking=()):
    return [make_tag(n, thinking=n in thinking) for n in names]


def judge_calls(fake):
    return [c for c in fake.calls if c[0] == "chat" and c[4] is not None]  # only judge requests send a JSON schema


def gen_result(c, run_id, model, category="generation"):
    rs = c.get(f"/api/runs/{run_id}/results").json()["results"]
    return next(r for r in rs if r["model"] == model and r["category"] == category)


def run_cross(c, models, cases=(GEN,), **kw):
    run = start_run(
        c, list(models), list(cases), judge_mode="cross_model", config={"warmup": False, **kw.pop("config", {})}, **kw
    )
    return run["id"], wait_for(c, run["id"], timeout=30)


# ---------------------------------------------------------------- 3.2 execution and aggregation
def test_two_models_judge_each_other(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid, done = run_cross(c, ["a:1", "b:1"])
        assert done["status"] == "completed"
        a, b = gen_result(c, rid, "a:1"), gen_result(c, rid, "b:1")
    # a:1's answer was judged by b:1 (0.25); b:1's answer by a:1 (0.75). Nobody judged themselves.
    assert a["primary"] == {"value": pytest.approx(0.25), "outcome": "judged"}
    assert b["primary"] == {"value": pytest.approx(0.75), "outcome": "judged"}
    da = next(s for s in a["scores"] if s["kind"] == "judge")["detail"]
    assert da["mode"] == "cross_model" and da["self_judged"] is False and da["judges_used"] == 1
    assert [j["judge_model"] for j in da["judgements"]] == ["b:1"]
    assert da["judgements"][0]["criteria"]["Relevance"] == {"score": 2, "reason": "scored by b:1"}
    assert [j["judge_model"] for j in next(s for s in b["scores"] if s["kind"] == "judge")["detail"]["judgements"]] == [
        "a:1"
    ]


def test_three_models_average_the_two_other_judges(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid, _ = run_cross(c, ["a:1", "b:1", "c:1"])
        got = {m: gen_result(c, rid, m) for m in ("a:1", "b:1", "c:1")}
    # a judged by b(.25)+c(1.0), b by a(.75)+c(1.0), c by a(.75)+b(.25)
    assert got["a:1"]["primary"]["value"] == pytest.approx((0.25 + 1.0) / 2)
    assert got["b:1"]["primary"]["value"] == pytest.approx((0.75 + 1.0) / 2)
    assert got["c:1"]["primary"]["value"] == pytest.approx((0.75 + 0.25) / 2)
    for m, r in got.items():
        judges = [
            j["judge_model"] for j in next(s for s in r["scores"] if s["kind"] == "judge")["detail"]["judgements"]
        ]
        assert sorted(judges) == sorted({"a:1", "b:1", "c:1"} - {m}) and m not in judges


def test_one_failing_judge_is_recorded_and_the_other_still_counts(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder(garbage={"a:1"}))
    with new_client(settings, file_session_factory, fake) as c:
        rid, done = run_cross(c, ["a:1", "b:1", "c:1"])
        b = gen_result(c, rid, "b:1")  # judged by a (garbage) and c (1.0)
    assert done["status"] == "completed"
    d = next(s for s in b["scores"] if s["kind"] == "judge")["detail"]
    assert b["primary"] == {"value": 1.0, "outcome": "judged"} and d["judges_used"] == 1
    by_judge = {j["judge_model"]: j for j in d["judgements"]}
    assert by_judge["a:1"]["outcome"] == "error" and "JSON" in by_judge["a:1"]["error"]
    assert by_judge["c:1"]["outcome"] == "judged"


def test_all_judges_failing_is_an_error_excluded_from_category_means(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder(garbage={"a:1", "b:1"}))
    with new_client(settings, file_session_factory, fake) as c:
        rid, done = run_cross(c, ["a:1", "b:1"], cases=(CLS, GEN))
        a = gen_result(c, rid, "a:1")
        summary = c.get(f"/api/runs/{rid}/summary").json()
    assert done["status"] == "completed"  # the run itself is not failed
    assert a["primary"]["outcome"] == "error" and a["primary"]["value"] is None
    row = summary["leaderboard"][0]
    assert row["categories"]["generation"]["score"] is None and row["categories"]["generation"]["scored"] == 0
    assert row["composite"] == row["categories"]["classification"]["score"]


def test_single_judge_output_shape_is_unchanged(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "j:1"), make_cross_responder(scores={"j:1": 4}))
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [GEN], judge_model="j:1", config={"warmup": False})
        wait_for(c, run["id"])
        d = next(s for s in gen_result(c, run["id"], "a:1")["scores"] if s["kind"] == "judge")["detail"]
    assert d["criteria"]["Relevance"]["score"] == 4 and d["raw_mean"] == 4.0 and d["judge_model"] == "j:1"
    assert d["self_judged"] is False and d["mode"] == "single" and d["judges_used"] == 1


def test_reasoning_quality_is_judged_across_models_when_enabled(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid, _ = run_cross(c, ["a:1", "b:1"], cases=(REA,), config={"judge_reasoning": True})
        r = gen_result(c, rid, "a:1", "reasoning")
        sc = next(s for s in r["scores"] if s["kind"] == "judge_reasoning")
    assert sc["detail"]["mode"] == "cross_model" and [j["judge_model"] for j in sc["detail"]["judgements"]] == ["b:1"]
    assert r["primary"]["outcome"] == "correct"  # correctness scoring is untouched by judging


# ---------------------------------------------------------------- 3.3 order and resources
def test_judging_is_grouped_by_judge_after_all_generation_with_unloads(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1", thinking=("a:1",)), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid, _ = run_cross(c, ["a:1", "b:1", "c:1"], cases=(GEN, GEN))
    log = [(k[0], k[1], len(k) > 4 and k[4] is not None) for k in fake.calls]  # (kind, model, is_judge_request)
    first_judge = next(i for i, e in enumerate(log) if e[0] == "chat" and e[2])
    assert not any(e[0] == "chat" and e[2] for e in log[:first_judge])
    assert all(e[0] == "chat" and not e[2] or e[0] == "unload" for e in log[:first_judge])  # only generation before
    judge_models = [e[1] for e in log[first_judge:] if e[0] == "chat"]
    groups = [m for i, m in enumerate(judge_models) if i == 0 or judge_models[i - 1] != m]
    assert groups == ["a:1", "b:1", "c:1"]  # each judge appears exactly once, contiguously
    # 2 answers per model x 2 other judges each = 4 judgements per judge... (2 cases x 2 other models)
    assert [judge_models.count(m) for m in ("a:1", "b:1", "c:1")] == [4, 4, 4]
    tail = [(e[0], e[1]) for e in log[first_judge:] if e[0] == "unload"]
    assert tail == [("unload", "a:1"), ("unload", "b:1")]  # previous judge unloaded before the next loads
    # a:1 is thinking-capable: thinking off for its judge calls; the others leave it unset
    assert {k[3] for k in judge_calls(fake) if k[1] == "a:1"} == {False}
    assert {k[3] for k in judge_calls(fake) if k[1] in ("b:1", "c:1")} == {None}


def test_failed_requests_are_never_sent_to_a_judge(settings, file_session_factory):
    from app.ollama.client import OllamaError

    base = make_cross_responder()

    def responder(model, messages, options):
        if model == "a:1" and not is_judge_request(messages) and "haiku" in messages[-1]["content"]:
            raise OllamaError("runner crashed")
        return base(model, messages, options)

    fake = FakeOllama(tags("a:1", "b:1"), responder)
    with new_client(settings, file_session_factory, fake) as c:
        rid, done = run_cross(c, ["a:1", "b:1"])
        a, b = gen_result(c, rid, "a:1"), gen_result(c, rid, "b:1")
    assert done["status"] == "completed"
    assert a["status"] == "error" and a["primary"] == {"value": 0.0, "outcome": "error"}
    assert [k[1] for k in judge_calls(fake)] == ["a:1"]  # only b's answer was judged (by a); a's failed request wasn't
    assert b["primary"]["outcome"] == "judged"


def test_judge_connection_loss_fails_the_run_but_keeps_earlier_judgements(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder(unreachable={"b:1"}))
    with new_client(settings, file_session_factory, fake) as c:
        rid, done = run_cross(c, ["a:1", "b:1"])
        b = gen_result(c, rid, "b:1")
        a = gen_result(c, rid, "a:1")
    assert done["status"] == "failed" and "connection lost" in done["error"]
    assert b["primary"]["outcome"] == "judged"  # a:1 judged b's answer before b:1's connection dropped
    assert a["primary"]["outcome"] == "unscored"  # b:1 never got to judge a's answer


# ---------------------------------------------------------------- 3.4 cancellation and speed isolation
def test_cancel_during_judging_keeps_completed_judgements(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder())
    fake.judge_chunk_delay_s = 0.03  # judging is slow enough for the cancel to land mid-stage
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1", "c:1"], [GEN, GEN, GEN], judge_mode="cross_model", config={"warmup": False})
        rid = run["id"]
        deadline = time.time() + 30
        while len(judge_calls(fake)) < 3 and time.time() < deadline:
            time.sleep(0.002)
        assert c.post(f"/api/runs/{rid}/cancel").json()["status"] == "cancelling"
        done = wait_for(c, rid, timeout=30)
        results = c.get(f"/api/runs/{rid}/results").json()["results"]
    total_judgements = 3 * 3 * 2
    made = len(judge_calls(fake))
    assert done["status"] == "cancelled" and 3 <= made < total_judgements
    judged = [r for r in results if r["primary"]["outcome"] == "judged"]
    assert judged, "answers judged before the cancel keep their aggregate score"
    counted = sum(next(s for s in r["scores"] if s["kind"] == "judge")["detail"]["judges_used"] for r in judged)
    assert made - 1 <= counted <= made  # every finished judgement is stored (the aborted in-flight one is not)
    assert len(judged) < len(results)  # the rest stay unjudged


def test_judging_never_appears_in_the_evaluated_models_speed_figures(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid, _ = run_cross(c, ["a:1", "b:1"], cases=(CLS, GEN))
        s = c.get(f"/api/runs/{rid}/summary").json()
    chats = [k for k in fake.calls if k[0] == "chat"]
    n_gen = 4
    assert all(k[4] is None for k in chats[:n_gen]) and all(
        k[4] is not None for k in chats[n_gen:]
    )  # judging strictly after
    assert {r["model"] for r in s["leaderboard"]} == {"a:1", "b:1"}
    assert all(r["performance"]["requests"] == 2 for r in s["leaderboard"])  # 2 cases each, no judge traffic
    assert s["attempt"] is not None


def test_scoring_progress_counts_every_judgement(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1", "c:1"), make_cross_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1", "c:1"], [GEN], judge_mode="cross_model", config={"warmup": False})
        with c.stream("GET", f"/api/runs/{run['id']}/events") as resp:
            body = "".join(resp.iter_text())
    prog = [json.loads(ln[6:]) for ln in body.splitlines() if ln.startswith("data: ") and '"done"' in ln]
    assert [p["done"] for p in prog] == [1, 2, 3, 4, 5, 6] and {p["total"] for p in prog} == {6}  # 3 answers x 2 judges
    assert '"judge_mode": "cross_model"' in body  # scoring_started announces the mode


# ---------------------------------------------------------------- 3.5 judge no longer installed
def test_rescore_with_an_uninstalled_judge_records_errors_and_continues(settings, file_session_factory):
    fake = FakeOllama(tags("a:1", "b:1"), make_cross_responder(), strict_models=True)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [GEN], judge_model="a:1", config={"warmup": False})
        wait_for(c, run["id"])
        fake._models = [m for m in fake._models if m["name"] != "b:1"]  # b:1 is removed from Ollama
        assert c.post(f"/api/runs/{run['id']}/rescore", json={"judge_mode": "cross_model"}).status_code == 202
        wait_for(c, run["id"])
        a, b = gen_result(c, run["id"], "a:1"), gen_result(c, run["id"], "b:1")
    # a's answer had only b:1 as judge -> error; b's answer was judged by a:1 -> fine
    assert a["primary"]["outcome"] == "error"
    da = next(s for s in a["scores"] if s["kind"] == "judge")["detail"]
    assert da["judgements"][0]["judge_model"] == "b:1" and "not found" in da["judgements"][0]["error"]
    assert b["primary"] == {"value": pytest.approx(0.75), "outcome": "judged"}
