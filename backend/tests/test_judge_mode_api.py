"""2.1: judging mode validation on run creation."""

import pytest

from app.core.scoring.judging import resolve_judging
from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS, GEN, make_responder, new_client, start_run, wait_for


def models3():
    return [make_tag("a:1"), make_tag("b:1"), make_tag("judge:1")]


# ---------------------------------------------------------------- the matrix, as a pure function
@pytest.mark.parametrize(
    "mode,judge,names,expected",
    [
        (None, None, ["a"], ("none", None)),
        (None, "j", ["a"], ("single", "j")),  # omitted mode inferred from judge_model
        ("single", "j", ["a"], ("single", "j")),
        ("none", None, ["a", "b"], ("none", None)),
        ("cross_model", None, ["a", "b"], ("cross_model", None)),
        ("cross_model", None, ["a", "b", "c"], ("cross_model", None)),
    ],
)
def test_valid_combinations(mode, judge, names, expected):
    assert resolve_judging(mode, judge, names) == expected


@pytest.mark.parametrize(
    "mode,judge,names,fragment",
    [
        ("single", None, ["a"], "needs a judge model"),
        ("none", "j", ["a"], "judging mode is 'none'"),
        ("cross_model", "j", ["a", "b"], "remove the judge model"),
        ("cross_model", None, ["a"], "at least two"),
        ("cross_model", None, ["a", "a"], "at least two"),  # duplicates are one model
        ("cross_model", None, [], "at least two"),
        ("weird", None, ["a"], "Unknown judging mode"),
    ],
)
def test_invalid_combinations(mode, judge, names, fragment):
    with pytest.raises(ValueError, match=fragment):
        resolve_judging(mode, judge, names)


# ---------------------------------------------------------------- through the API
def post(c, **body):
    return c.post("/api/runs", json={"adhoc_cases": [GEN], **body})


def test_every_row_of_the_matrix_over_http(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(models3(), make_responder())) as c:
        ok = post(c, models=["a:1", "b:1"], judge_mode="cross_model", config={"warmup": False})
        assert ok.status_code == 201 and ok.json()["judge_mode"] == "cross_model" and ok.json()["judge_model"] is None
        wait_for(c, ok.json()["id"])

        legacy = post(c, models=["a:1"], judge_model="judge:1", config={"warmup": False})
        assert legacy.status_code == 201 and legacy.json()["judge_mode"] == "single"
        wait_for(c, legacy.json()["id"])
        none = post(c, models=["a:1"], config={"warmup": False})
        assert none.json()["judge_mode"] == "none"
        wait_for(c, none.json()["id"])

        n_before = len(c.get("/api/runs").json())
        cases = [
            (dict(models=["a:1"], judge_mode="single"), "needs a judge model"),
            (dict(models=["a:1"], judge_mode="none", judge_model="judge:1"), "judging mode is 'none'"),
            (dict(models=["a:1", "b:1"], judge_mode="cross_model", judge_model="judge:1"), "remove the judge model"),
            (dict(models=["a:1"], judge_mode="cross_model"), "at least two"),
            (dict(models=["a:1", "a:1"], judge_mode="cross_model"), "at least two"),
        ]
        for body, fragment in cases:
            r = post(c, **body)
            assert r.status_code == 422, body
            d = r.json()["detail"]
            assert d["code"] == "invalid_judging" and fragment in d["message"], (body, d)
        assert len(c.get("/api/runs").json()) == n_before  # nothing was created

        assert post(c, models=["a:1"], judge_mode="bogus").status_code == 422  # not one of the three modes


def test_cross_model_does_not_require_a_judge_model_to_be_installed(settings, file_session_factory):
    with new_client(
        settings, file_session_factory, FakeOllama([make_tag("a:1"), make_tag("b:1")], make_responder())
    ) as c:
        r = post(c, models=["a:1", "b:1"], judge_mode="cross_model", config={"warmup": False})
        assert r.status_code == 201
        wait_for(c, r.json()["id"])


def test_single_judge_must_still_be_installed(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(models3(), make_responder())) as c:
        r = post(c, models=["a:1"], judge_model="ghost:1")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "model_not_installed"


def test_mode_is_listed_on_runs(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(models3(), make_responder())) as c:
        run = start_run(c, ["a:1", "b:1"], [CLS], judge_mode="cross_model", config={"warmup": False})
        wait_for(c, run["id"])
        assert c.get("/api/runs").json()[0]["judge_mode"] == "cross_model"
        assert c.get(f"/api/runs/{run['id']}").json()["judge_mode"] == "cross_model"


# ---------------------------------------------------------------- 2.2 re-run and re-score
def test_rerun_copies_mode_and_judge(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(models3(), make_responder())) as c:
        cross = start_run(c, ["a:1", "b:1"], [GEN], judge_mode="cross_model", config={"warmup": False})
        wait_for(c, cross["id"])
        again = c.post(f"/api/runs/{cross['id']}/rerun").json()
        assert again["judge_mode"] == "cross_model" and again["judge_model"] is None
        assert [m["name"] for m in again["models"]] == ["a:1", "b:1"] and again["parent_run_id"] == cross["id"]
        wait_for(c, again["id"])

        single = start_run(c, ["a:1"], [GEN], judge_model="judge:1", config={"warmup": False})
        wait_for(c, single["id"])
        again2 = c.post(f"/api/runs/{single['id']}/rerun").json()
        assert again2["judge_mode"] == "single" and again2["judge_model"] == "judge:1"
        wait_for(c, again2["id"])


def test_rescore_accepts_a_mode_and_rejects_cross_model_for_one_model(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama(models3(), make_responder())) as c:
        two = start_run(c, ["a:1", "b:1"], [GEN], judge_model="judge:1", config={"warmup": False})
        wait_for(c, two["id"])
        r = c.post(f"/api/runs/{two['id']}/rescore", json={"judge_mode": "cross_model"})
        assert r.status_code == 202
        wait_for(c, two["id"])

        one = start_run(c, ["a:1"], [GEN], judge_model="judge:1", config={"warmup": False})
        wait_for(c, one["id"])
        r = c.post(f"/api/runs/{one['id']}/rescore", json={"judge_mode": "cross_model"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_judging" and "at least two" in r.json()["detail"]["message"]
        r = c.post(f"/api/runs/{two['id']}/rescore", json={"judge_mode": "cross_model", "judge_model": "judge:1"})
        assert r.status_code == 422 and "remove the judge model" in r.json()["detail"]["message"]
        r = c.post(f"/api/runs/{one['id']}/rescore", json={"judge_mode": "single"})
        assert r.status_code == 422 and "needs a judge model" in r.json()["detail"]["message"]
        # legacy body (judge_model only) still means single
        assert c.post(f"/api/runs/{one['id']}/rescore", json={"judge_model": "judge:1"}).status_code == 202
        wait_for(c, one["id"])
