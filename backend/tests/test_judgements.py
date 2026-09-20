"""1.2: judgement storage and aggregation."""

from types import SimpleNamespace as NS

import pytest

from app import repo
from app.core.scoring.judging import aggregate_judgements, rebuild_aggregate
from app.repo import CaseSource
from app.schemas import CaseIn, ModelInfo


def J(model, value, outcome="judged", **detail):
    return NS(judge_model=model, value=value, outcome=outcome, detail=detail)


def test_mean_of_successful_judgements():
    agg = aggregate_judgements([J("a", 0.5), J("b", 0.75)], kind="judge", mode="cross_model")
    assert agg.value == pytest.approx(0.625) and agg.outcome == "judged"
    assert agg.detail["judges_used"] == 2 and agg.detail["self_judged"] is False
    assert [j["judge_model"] for j in agg.detail["judgements"]] == ["a", "b"]


def test_one_failed_judge_is_recorded_but_ignored_in_the_mean():
    agg = aggregate_judgements(
        [J("a", 0.5, criteria={"X": {"score": 3, "reason": "ok"}}), J("b", None, "error", error="bad json")],
        kind="judge",
        mode="cross_model",
    )
    assert agg.value == 0.5 and agg.outcome == "judged" and agg.detail["judges_used"] == 1
    failed = agg.detail["judgements"][1]
    assert failed["outcome"] == "error" and failed["error"] == "bad json"
    assert agg.detail["judgements"][0]["criteria"]["X"]["score"] == 3


def test_all_judges_failed_is_an_error_with_no_value():
    agg = aggregate_judgements(
        [J("a", None, "error", error="x"), J("b", None, "error", error="y")], kind="judge", mode="cross_model"
    )
    assert agg.value is None and agg.outcome == "error" and agg.detail["judges_used"] == 0
    assert "a: x" in agg.detail["error"] and "b: y" in agg.detail["error"]


def test_single_mode_keeps_the_flat_detail_shape():
    d = {
        "criteria": {"R": {"score": 4, "reason": "r"}},
        "raw_mean": 4.0,
        "judge_model": "j",
        "attempts": 1,
        "self_judged": True,
    }
    agg = aggregate_judgements([J("j", 0.75, **d)], kind="judge", mode="single")
    assert agg.detail["criteria"] == d["criteria"] and agg.detail["self_judged"] is True
    assert agg.detail["raw_mean"] == 4.0 and agg.detail["mode"] == "single" and len(agg.detail["judgements"]) == 1


def test_single_mode_error_is_preserved():
    agg = aggregate_judgements([J("j", None, "error", error="boom", judge_model="j")], kind="judge", mode="single")
    assert agg.outcome == "error" and agg.detail["error"] == "boom"


@pytest.fixture
def scored(session):
    snap = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d"))
    case = CaseIn(category="generation", prompt="x")
    run = repo.create_run(session, name="r", config={}, judge_model=None, snapshots=[snap], cases=[CaseSource(case)])
    res = repo.add_result(session, run_id=run.id, model_snapshot_id=snap.id, run_case_id=run.cases[0].id, output="o")
    att = repo.create_attempt(session, run.id, None, "cross_model")
    return run, res, att


def test_attempt_and_run_record_the_mode(session):
    snap = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d"))
    case = [CaseSource(CaseIn(category="generation", prompt="x"))]
    single = repo.create_run(session, name="r", config={}, judge_model="j", snapshots=[snap], cases=case)
    none = repo.create_run(session, name="r", config={}, judge_model=None, snapshots=[snap], cases=case)
    cross = repo.create_run(
        session, name="r", config={}, judge_model=None, snapshots=[snap], cases=case, judge_mode="cross_model"
    )
    assert (single.judge_mode, none.judge_mode, cross.judge_mode) == ("single", "none", "cross_model")
    assert repo.create_attempt(session, single.id, "j").judge_mode == "single"
    assert repo.create_attempt(session, single.id, None, "cross_model").judge_mode == "cross_model"


def test_rebuild_aggregate_from_stored_judgements_is_idempotent(session, scored):
    run, res, att = scored
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge",
        judge_model="a",
        value=0.5,
        outcome="judged",
        detail={"criteria": {}},
    )
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge",
        judge_model="b",
        value=1.0,
        outcome="judged",
        detail={},
    )
    for _ in range(3):
        agg = rebuild_aggregate(session, attempt_id=att.id, result_id=res.id, kind="judge", mode="cross_model")
    assert agg.value == pytest.approx(0.75)
    rows = repo.list_scores(session, run.id, att.id)
    assert len(rows) == 1 and rows[0].kind == "judge" and rows[0].value == pytest.approx(0.75)

    # a late third judgement changes the aggregate in place
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge",
        judge_model="c",
        value=0.0,
        outcome="judged",
        detail={},
    )
    rebuild_aggregate(session, attempt_id=att.id, result_id=res.id, kind="judge", mode="cross_model")
    rows = repo.list_scores(session, run.id, att.id)
    assert len(rows) == 1 and rows[0].value == pytest.approx(0.5) and rows[0].detail["judges_used"] == 3


def test_rebuild_with_no_judgements_writes_nothing(session, scored):
    run, res, att = scored
    assert rebuild_aggregate(session, attempt_id=att.id, result_id=res.id, kind="judge", mode="cross_model") is None
    assert repo.list_scores(session, run.id, att.id) == []


def test_reasoning_and_generation_kinds_are_kept_apart(session, scored):
    run, res, att = scored
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge",
        judge_model="a",
        value=1.0,
        outcome="judged",
        detail={},
    )
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge_reasoning",
        judge_model="a",
        value=0.0,
        outcome="judged",
        detail={},
    )
    rebuild_aggregate(session, attempt_id=att.id, result_id=res.id, kind="judge", mode="cross_model")
    rebuild_aggregate(session, attempt_id=att.id, result_id=res.id, kind="judge_reasoning", mode="cross_model")
    by_kind = {s.kind: s.value for s in repo.list_scores(session, run.id, att.id)}
    assert by_kind == {"judge": 1.0, "judge_reasoning": 0.0}


def test_judgements_are_deleted_with_their_run(session, scored):
    run, res, att = scored
    repo.add_judgement(
        session,
        attempt_id=att.id,
        result_id=res.id,
        kind="judge",
        judge_model="a",
        value=1.0,
        outcome="judged",
        detail={},
    )
    repo.delete_run(session, run.id)
    session.expire_all()
    assert repo.list_judgements(session, att.id) == []
