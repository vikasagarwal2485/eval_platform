import pytest

from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS, GEN, REA, make_responder, new_client, start_run, two_models, wait_for


def scenario(c, models=("a:1",), **kw):
    run = start_run(c, list(models), [CLS, REA, GEN], config={"warmup": False}, judge_model="a:1", **kw)
    wait_for(c, run["id"])
    return run["id"]


def responder():
    # a:1 gets classification right, reasoning wrong, generation judged 0.75; b:1 answers everything right
    return make_responder({"a:1": {"What is 2+3": "Final answer: 6"}})


def test_leaderboard_rows_scores_counts_and_performance(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(two_models(), responder())) as c:
        rid = scenario(c, ("a:1", "b:1"))
        s = c.get(f"/api/runs/{rid}/summary").json()
    assert s["comparable"] is True and s["models_count"] == 2
    assert s["categories_present"] == ["classification", "reasoning", "generation"]
    a, b = s["leaderboard"]
    assert a["model"] == "a:1"
    assert a["categories"]["classification"] == {"score": 1.0, "scored": 1, "total": 1, "errors": 0, "unparseable": 0}
    assert a["categories"]["reasoning"]["score"] == 0.0 and b["categories"]["reasoning"]["score"] == 1.0
    assert a["categories"]["generation"]["score"] == pytest.approx(0.75)
    assert a["composite"] == pytest.approx((1.0 + 0.0 + 0.75) / 3) and b["composite"] == pytest.approx(
        (1 + 1 + 0.75) / 3
    )
    assert a["performance"]["requests"] == 3 and a["performance"]["warm_requests"] == 3
    assert a["performance"]["tokens_per_s"]["mean"] and a["performance"]["latency_ms"]["median"] is not None
    assert set(a["performance_by_category"]) == {"classification", "reasoning", "generation"}
    assert a["classification"]["accuracy"] == 1.0
    assert a["constraints"] == {"passed": 1, "total": 1} and a["self_judged"] is True


def test_changing_weights_recomputes_composite_without_rerunning(settings, file_session_factory):
    fake = FakeOllama(two_models(), responder())
    with new_client(settings, file_session_factory, fake) as c:
        rid = scenario(c, ("a:1", "b:1"))
        calls_before = len(fake.calls)
        get = lambda w: {
            r["model"]: r["composite"] for r in c.get(f"/api/runs/{rid}/summary?weights={w}").json()["leaderboard"]
        }
        w1 = get("classification:0.4,reasoning:0.4,generation:0.2")
        w2 = get("classification:0,reasoning:1,generation:0")
        w3 = get("classification:1")
        assert len(fake.calls) == calls_before
    assert w1["a:1"] == pytest.approx(0.4 * 1 + 0.4 * 0 + 0.2 * 0.75)
    assert w2 == {"a:1": 0.0, "b:1": 1.0}  # ranking flips with weights
    assert w3 == {"a:1": 1.0, "b:1": 1.0}


@pytest.mark.parametrize(
    "bad", ["foo:1", "classification:x", "classification:-1", "classification:0,reasoning:0,generation:0"]
)
def test_invalid_weights_rejected(settings, file_session_factory, bad):
    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], responder())) as c:
        rid = scenario(c)
        assert c.get(f"/api/runs/{rid}/summary?weights={bad}").status_code == 422


def test_single_model_run_has_absolute_scores_and_is_not_comparable(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], responder())) as c:
        rid = scenario(c)
        s = c.get(f"/api/runs/{rid}/summary").json()
    assert s["comparable"] is False and len(s["leaderboard"]) == 1
    assert s["leaderboard"][0]["composite"] is not None


def test_missing_category_renormalizes_composite(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], responder())) as c:
        run = start_run(c, ["a:1"], [CLS, GEN], config={"warmup": False}, judge_model="a:1")
        wait_for(c, run["id"])
        row = c.get(f"/api/runs/{run['id']}/summary?weights=classification:0.4,reasoning:0.4,generation:0.2").json()[
            "leaderboard"
        ][0]
    assert "reasoning" not in row["categories"]
    assert row["composite"] == pytest.approx((0.4 * 1.0 + 0.2 * 0.75) / 0.6)


def test_cold_requests_excluded_by_default_and_includable(settings, file_session_factory):
    from tests.fakes import make_stream

    calls = {"n": 0}

    def resp(model, messages, options):
        calls["n"] += 1
        return make_stream("positive", load_duration_ns=3_000_000_000 if calls["n"] == 1 else 10_000_000)

    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], resp)) as c:
        run = start_run(c, ["a:1"], [CLS, CLS, CLS], config={"warmup": False})
        wait_for(c, run["id"])
        default = c.get(f"/api/runs/{run['id']}/summary").json()["leaderboard"][0]["performance"]
        incl = c.get(f"/api/runs/{run['id']}/summary?include_cold=true").json()["leaderboard"][0]["performance"]
    assert (default["cold_requests"], default["warm_requests"], default["latency_ms"]["n"]) == (1, 2, 2)
    assert incl["latency_ms"]["n"] == 3 and default["cold_load_ms"]["mean"] == pytest.approx(3000.0)


def test_results_filters(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(two_models(), responder())) as c:
        rid = scenario(c, ("a:1", "b:1"))
        get = lambda q: c.get(f"/api/runs/{rid}/results?{q}").json()["results"]
        assert len(get("")) == 6
        assert {r["model"] for r in get("model=b:1")} == {"b:1"}
        wrong = get("outcome=wrong")
        assert [(r["model"], r["category"]) for r in wrong] == [("a:1", "reasoning")]
        assert len(get("category=generation")) == 2
