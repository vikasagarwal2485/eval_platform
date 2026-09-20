import pytest

from app.ollama.client import OllamaError, OllamaUnreachable
from tests.fakes import FakeOllama, make_stream, make_tag
from tests.helpers import CLS, GEN, REA, judge_reply, make_responder, new_client, start_run, two_models, wait_for


def chat_models(fake: FakeOllama) -> list[str]:
    return [c[1] for c in fake.calls if c[0] == "chat"]


# ------------------------------------------------------------------ 6.1 creation & validation
def test_create_run_validation(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(two_models())) as c:
        r = c.post("/api/runs", json={"adhoc_cases": [CLS]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "no_models"
        r = c.post("/api/runs", json={"models": ["a:1"]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "no_cases"
        r = c.post("/api/runs", json={"models": ["nope:1"], "adhoc_cases": [CLS]})
        assert r.status_code == 422 and r.json()["detail"]["models"] == ["nope:1"]
        r = c.post("/api/runs", json={"models": ["a:1"], "adhoc_cases": [CLS], "judge_model": "ghost"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "model_not_installed"
        for bad in ({"temperature": 5}, {"repeats": 0}, {"repeats": 99}, {"max_output_tokens": 1}, {"bogus": 1}):
            r = c.post("/api/runs", json={"models": ["a:1"], "adhoc_cases": [CLS], "config": bad})
            assert r.status_code == 422, bad
        assert c.get("/api/runs").json() == []


def test_ollama_down_returns_503(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(down=True)) as c:
        r = c.post("/api/runs", json={"models": ["a:1"], "adhoc_cases": [CLS]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ollama_unreachable"


def test_defaults_and_frozen_records(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1", thinking=True)], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS])
        cfg = run["config"]
        assert (cfg["temperature"], cfg["seed"], cfg["repeats"], cfg["warmup"]) == (0.0, 42, 1, True)
        done = wait_for(c, run["id"])
        m = done["models"][0]
        assert (m["name"], m["parameter_size"], m["quantization"]) == ("a:1", "8B", "Q4_K_M") and m["digest"]
        assert done["cases"][0]["prompt"] == "I love it" and done["cases"][0]["expected"] == "positive"
        assert done["ollama_version"] == "0.34.2"


def test_run_from_suite_with_exclusions_and_no_duplicates(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        starter = next(s for s in c.get("/api/suites").json() if s["is_builtin"])
        cases = c.get(f"/api/suites/{starter['id']}").json()["cases"]
        skip, extra = cases[0]["id"], cases[1]["id"]
        r = c.post(
            "/api/runs",
            json={
                "models": ["a:1", "a:1"],
                "suite_ids": [starter["id"]],
                "exclude_case_ids": [skip],
                "case_ids": [extra],
            },
        )
        assert r.status_code == 201
        run = r.json()
        assert len(run["models"]) == 1 and run["case_count"] == len(cases) - 1  # dup model & case collapsed
        c.post(f"/api/runs/{run['id']}/cancel")
        wait_for(c, run["id"])


# ------------------------------------------------------------------ 6.2 sequential, model-grouped
def test_all_requests_for_model_a_precede_model_b(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS, REA, GEN], config={"repeats": 2, "warmup": False})
        done = wait_for(c, run["id"])
        assert done["status"] == "completed" and done["progress"] == {"completed": 12, "total": 12}
    order = chat_models(fake)
    first_b = order.index("b:1")
    assert set(order[:first_b]) == {"a:1"} and set(order[first_b:]) == {"b:1"}
    assert order.count("a:1") == order.count("b:1") == 6


def test_second_run_waits_and_never_overlaps(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder(), chunk_delay_s=0.02)
    with new_client(settings, file_session_factory, fake) as c:
        r1 = start_run(c, ["a:1"], [CLS, REA], config={"warmup": False})
        r2 = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        assert c.get(f"/api/runs/{r2['id']}").json()["status"] == "queued"
        d1, d2 = wait_for(c, r1["id"]), wait_for(c, r2["id"])
        assert d1["status"] == d2["status"] == "completed"
        assert d1["finished_at"] <= d2["started_at"]
        assert c.app.state.runner.max_concurrent_jobs == 1


# ------------------------------------------------------------------ 6.3 failure isolation
def test_model_error_is_recorded_and_run_continues(settings, file_session_factory):
    def responder(model, messages, options):
        if "What is 2+3" in messages[-1]["content"]:
            raise OllamaError("model runner has unexpectedly stopped")
        return make_stream("positive")

    fake = FakeOllama([make_tag("a:1")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [REA, CLS], config={"warmup": False})
        done = wait_for(c, run["id"])
        assert done["status"] == "completed"
        res = {r["category"]: r for r in c.get(f"/api/runs/{run['id']}/results").json()["results"]}
    assert res["reasoning"]["status"] == "error" and "stopped" in res["reasoning"]["error"]
    assert res["reasoning"]["primary"] == {"value": 0.0, "outcome": "error"}
    assert res["reasoning"]["latency_ms"] is None  # absent, not zero
    assert res["classification"]["status"] == "ok" and res["classification"]["primary"]["outcome"] == "correct"


def test_request_timeout_is_recorded_and_run_continues(settings, file_session_factory):
    def responder(model, messages, options):
        if "What is 2+3" in messages[-1]["content"]:
            return make_stream(" ".join(["w"] * 40))
        return make_stream("positive")

    class Slow(FakeOllama):
        async def chat_stream(self, **kw):
            self.chunk_delay_s = 0.05 if "2+3" in kw["messages"][-1]["content"] else 0
            async for ch in super().chat_stream(**kw):
                yield ch

    fake = Slow([make_tag("a:1")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [REA, CLS], config={"warmup": False, "request_timeout_s": 0.3})
        done = wait_for(c, run["id"])
        res = {r["category"]: r for r in c.get(f"/api/runs/{run['id']}/results").json()["results"]}
    assert done["status"] == "completed"
    assert res["reasoning"]["status"] == "error" and "timed out" in res["reasoning"]["error"]
    assert res["classification"]["status"] == "ok"


def test_disconnect_mid_run_fails_run_but_keeps_completed_results(settings, file_session_factory):
    calls = {"n": 0}

    def responder(model, messages, options):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OllamaUnreachable("connection refused")
        return make_stream("positive")

    fake = FakeOllama([make_tag("a:1")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS, CLS, CLS], config={"warmup": False})
        done = wait_for(c, run["id"])
        results = c.get(f"/api/runs/{run['id']}/results").json()["results"]
    assert done["status"] == "failed" and "unreachable" in done["error"].lower()
    assert [r["status"] for r in results] == ["ok", "error"]  # stopped after retries; 3rd never ran
    assert calls["n"] == 1 + 1 + settings.max_retries  # retried before giving up


def test_transient_disconnect_is_retried(settings, file_session_factory):
    calls = {"n": 0}

    def responder(model, messages, options):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OllamaUnreachable("blip")
        return make_stream("positive")

    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], responder)) as c:
        run = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        assert wait_for(c, run["id"])["status"] == "completed"
        assert c.get(f"/api/runs/{run['id']}/results").json()["results"][0]["status"] == "ok"


# ------------------------------------------------------------------ 6.4 unload & warm-up order
def test_warmup_unload_ordering(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS])
        wait_for(c, run["id"])
    log = [(c[0], c[1]) for c in fake.calls]
    assert log == [("chat", "a:1"), ("chat", "a:1"), ("unload", "a:1"), ("chat", "b:1"), ("chat", "b:1")]
    warm = [c for c in fake.calls if c[0] == "chat"][0]
    assert warm[2]["num_predict"] == 16 and warm[2]["num_ctx"] == 8192  # same ctx: no reload after warm-up


def test_warmup_disabled_skips_it(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        wait_for(c, start_run(c, ["a:1"], [CLS], config={"warmup": False})["id"])
    assert len(fake.calls) == 1


# ------------------------------------------------------------------ 6.5 cancellation
def test_cancel_mid_run_keeps_completed_and_stops_further_requests(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder(), chunk_delay_s=0.05)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS] * 6, config={"warmup": False})
        while c.get(f"/api/runs/{run['id']}").json()["progress"]["completed"] < 2:
            pass
        assert c.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelling"
        done = wait_for(c, run["id"])
        results = c.get(f"/api/runs/{run['id']}/results").json()["results"]
        n_chat_at_cancel = len(chat_models(fake))
    assert done["status"] == "cancelled" and 2 <= len(results) < 6
    assert all(r["status"] == "ok" and r["primary"]["outcome"] == "correct" for r in results)  # still scored
    assert n_chat_at_cancel <= len(results) + 1  # at most the aborted in-flight request
    assert c.app.state.runner.max_concurrent_jobs == 1


def test_cancel_queued_run_never_starts(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder(), chunk_delay_s=0.03)
    with new_client(settings, file_session_factory, fake) as c:
        r1 = start_run(c, ["a:1"], [CLS, CLS, CLS], config={"warmup": False})
        r2 = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        assert c.post(f"/api/runs/{r2['id']}/cancel").json()["status"] == "cancelled"
        wait_for(c, r1["id"])
        assert c.get(f"/api/runs/{r2['id']}").json()["status"] == "cancelled"
        assert c.get(f"/api/runs/{r2['id']}/results").json()["results"] == []


def test_cancel_finished_run_conflicts(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], make_responder())) as c:
        run = start_run(c, ["a:1"], [CLS])
        wait_for(c, run["id"])
        assert c.post(f"/api/runs/{run['id']}/cancel").status_code == 409


# ------------------------------------------------------------------ 6.6 SSE
def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        ev = {}
        for line in block.splitlines():
            k, _, v = line.partition(": ")
            ev[k] = v
        if ev:
            events.append(ev)
    return events


def test_sse_progress_events_in_order_and_resync(settings, file_session_factory):
    import json

    fake = FakeOllama(two_models(), make_responder(), chunk_delay_s=0.01)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS, REA], config={"warmup": False})
        with c.stream("GET", f"/api/runs/{run['id']}/events") as resp:
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
        events = parse_sse(body)
        types = [e["event"] for e in events]
        assert types[0] == "state" and types[-1] == "run_finished"
        assert types.count("result_completed") == 4
        assert (
            types.index("run_started")
            < types.index("result_completed")
            < types.index("scoring_started")
            < types.index("run_finished")
        )
        ids = [int(e["id"]) for e in events if "id" in e]
        assert ids == sorted(ids)
        progress = [json.loads(e["data"])["completed"] for e in events if e["event"] == "progress"]
        assert progress == [1, 2, 3, 4]
        assert json.loads(events[-1]["data"])["status"] == "completed"
        assert any(e["event"] == "token" for e in events)
        # resync: the DB is the source of truth
        assert c.get(f"/api/runs/{run['id']}").json()["progress"]["completed"] == 4
        # reconnect after the run: state snapshot only, stream closes
        with c.stream("GET", f"/api/runs/{run['id']}/events?after=999999") as resp:
            again = parse_sse("".join(resp.iter_text()))
        assert [e["event"] for e in again] == ["state"]


def test_sse_last_event_id_replays_only_newer(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS, CLS], config={"warmup": False})
        wait_for(c, run["id"])
        with c.stream("GET", f"/api/runs/{run['id']}/events") as resp:
            full = parse_sse("".join(resp.iter_text()))
        mid = int(full[3]["id"])
        with c.stream("GET", f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": str(mid)}) as resp:
            tail = parse_sse("".join(resp.iter_text()))
    assert all(int(e["id"]) > mid for e in tail if "id" in e) and tail[-1]["event"] == "run_finished"


# ------------------------------------------------------------------ 6.7 history / re-run
def test_history_delete_and_rerun_links_to_original(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        cfg = {"temperature": 0.2, "seed": 7, "repeats": 2, "warmup": False, "max_output_tokens": 512}
        orig = start_run(c, ["a:1", "b:1"], [CLS, GEN], config=cfg, judge_model="a:1", name="baseline")
        wait_for(c, orig["id"])
        rr = c.post(f"/api/runs/{orig['id']}/rerun")
        assert rr.status_code == 201
        new = rr.json()
        assert new["parent_run_id"] == orig["id"] and new["id"] != orig["id"]
        wait_for(c, new["id"])
        got = c.get(f"/api/runs/{new['id']}").json()
        o = c.get(f"/api/runs/{orig['id']}").json()
        assert got["config"] == o["config"] == {**o["config"], **cfg}
        assert [m["name"] for m in got["models"]] == ["a:1", "b:1"] and got["judge_model"] == "a:1"
        assert [(x["prompt"], x["expected"]) for x in got["cases"]] == [
            (x["prompt"], x["expected"]) for x in o["cases"]
        ]
        assert [r["id"] for r in c.get("/api/runs").json()] == [new["id"], orig["id"]]  # newest first

        assert c.delete(f"/api/runs/{orig['id']}").status_code == 204
        assert c.get(f"/api/runs/{orig['id']}").status_code == 404
        assert c.get(f"/api/runs/{new['id']}").json()["parent_run_id"] is None  # link cleared, run intact


def test_cannot_delete_running_and_rerun_needs_models(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder(), chunk_delay_s=0.05)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS] * 4, config={"warmup": False})
        assert c.delete(f"/api/runs/{run['id']}").status_code == 409
        c.post(f"/api/runs/{run['id']}/cancel")
        wait_for(c, run["id"])
        fake._models.clear()
        assert c.post(f"/api/runs/{run['id']}/rerun").status_code == 409


# ------------------------------------------------------------------ 6.8 judge as post-generation stage
def test_judge_runs_after_all_generation_and_is_excluded_from_perf(settings, file_session_factory):
    fake = FakeOllama(two_models() + [make_tag("judge:1", thinking=True)], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS, GEN], config={"warmup": False}, judge_model="judge:1")
        wait_for(c, run["id"])
        summary = c.get(f"/api/runs/{run['id']}/summary").json()
        results = c.get(f"/api/runs/{run['id']}/results").json()["results"]
    order = chat_models(fake)
    first_judge = order.index("judge:1")
    assert set(order[:first_judge]) == {"a:1", "b:1"} and set(order[first_judge:]) == {"judge:1"}
    assert order.count("judge:1") == 2  # one per generation result
    judge_calls = [c for c in fake.calls if c[1] == "judge:1"]
    assert all(c[3] is False for c in judge_calls)  # thinking disabled for a thinking judge
    gen = next(r for r in results if r["category"] == "generation")
    judge = next(s for s in gen["scores"] if s["kind"] == "judge")
    assert judge["outcome"] == "judged" and judge["detail"]["judge_metrics"] and judge["value"] == pytest.approx(0.75)
    assert judge["detail"]["self_judged"] is False
    models = {r["model"] for r in summary["leaderboard"]}
    assert models == {"a:1", "b:1"}  # judge never appears in the comparison
    assert all(r["performance"]["requests"] == 2 for r in summary["leaderboard"])


def test_no_judge_leaves_generation_unscored_and_out_of_composite(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS, GEN], config={"warmup": False})
        wait_for(c, run["id"])
        row = c.get(f"/api/runs/{run['id']}/summary").json()["leaderboard"][0]
    assert row["categories"]["generation"]["score"] is None and row["categories"]["generation"]["scored"] == 0
    assert row["composite"] == row["categories"]["classification"]["score"] == 1.0


def test_self_judging_is_flagged(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [GEN], config={"warmup": False}, judge_model="a:1")
        wait_for(c, run["id"])
        row = c.get(f"/api/runs/{run['id']}/summary").json()["leaderboard"][0]
    assert row["self_judged"] is True


# ------------------------------------------------------------------ 5.9 rescore
def test_rescore_with_second_judge_keeps_results_and_first_attempt(settings, file_session_factory):
    replies = {"judge:1": judge_reply(2, 2), "judge:2": judge_reply(5, 5)}

    def responder(model, messages, options):
        if messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
            return make_stream(replies[model])
        return make_responder()(model, messages, options)

    fake = FakeOllama([make_tag("a:1"), make_tag("judge:1"), make_tag("judge:2")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS, GEN], config={"warmup": False}, judge_model="judge:1")
        wait_for(c, run["id"])
        before = c.get(f"/api/runs/{run['id']}/results").json()
        first_attempt = before["attempt_id"]
        assert c.post(f"/api/runs/{run['id']}/rescore", json={"judge_model": "judge:2"}).status_code == 202
        wait_for(c, run["id"])
        after = c.get(f"/api/runs/{run['id']}/results").json()
        old = c.get(f"/api/runs/{run['id']}/results?attempt={first_attempt}").json()
        s_new = c.get(f"/api/runs/{run['id']}/summary").json()
        s_old = c.get(f"/api/runs/{run['id']}/summary?attempt={first_attempt}").json()

    assert after["attempt_id"] != first_attempt
    strip = lambda rs: [{k: v for k, v in r.items() if k not in ("scores", "primary")} for r in rs["results"]]
    assert strip(before) == strip(after)  # outputs & metrics untouched
    gen = lambda rs: next(r for r in rs["results"] if r["category"] == "generation")["primary"]["value"]
    assert gen(after) == 1.0 and gen(old) == pytest.approx(0.25)  # both judgments readable
    assert s_new["attempt"]["judge_model"] == "judge:2" and s_old["attempt"]["judge_model"] == "judge:1"
    assert len(s_new["attempts"]) == 2
    assert s_new["leaderboard"][0]["performance"] == s_old["leaderboard"][0]["performance"]


def test_rescore_rules(settings, file_session_factory):
    fake = FakeOllama([make_tag("a:1")], make_responder(), chunk_delay_s=0.05)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS] * 3, config={"warmup": False})
        assert c.post(f"/api/runs/{run['id']}/rescore", json={}).status_code == 409  # still running
        wait_for(c, run["id"])
        assert c.post(f"/api/runs/{run['id']}/rescore", json={"judge_model": "ghost"}).status_code == 422


# ------------------------------------------------------------------ 7.3 footprint
def test_memory_footprint_recorded_per_model_after_warmup(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder())
    fake.ps_data = [
        {"name": "a:1", "size": 5_000_000_000, "size_vram": 4_000_000_000},
        {"name": "b:1", "size": 7_000_000_000, "size_vram": 7_000_000_000},
    ]
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS])
        wait_for(c, run["id"])
        got = {m["name"]: m["memory"] for m in c.get(f"/api/runs/{run['id']}").json()["models"]}
        board = {r["model"]: r["memory"] for r in c.get(f"/api/runs/{run['id']}/summary").json()["leaderboard"]}
    assert got["a:1"] == {"size": 5_000_000_000, "size_vram": 4_000_000_000}
    assert board["b:1"] == {"size": 7_000_000_000, "size_vram": 7_000_000_000}
