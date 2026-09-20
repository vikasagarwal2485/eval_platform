import pytest

from app import repo
from app.repo import CaseSource
from app.schemas import CaseIn, ModelInfo, SuiteIn


def cls_case(prompt="great!", expected="positive"):
    return CaseIn(category="classification", prompt=prompt, labels=["positive", "negative"], expected=expected)


def mk_suite(session, name="s"):
    return repo.create_suite(
        session,
        SuiteIn(
            name=name,
            cases=[
                cls_case(),
                CaseIn(category="reasoning", prompt="2+2", expected="4", comparison="numeric"),
                CaseIn(category="generation", prompt="haiku", rubric=[{"name": "form"}]),
            ],
        ),
    )


def test_suite_crud_and_mixed_categories(session):
    s = mk_suite(session)
    assert repo.suite_counts(s) == {"classification": 1, "reasoning": 1, "generation": 1}
    assert [c.position for c in s.cases] == [0, 1, 2]

    repo.update_suite(session, s.id, name="renamed", description="d")
    assert repo.get_suite(session, s.id).name == "renamed"

    row = repo.add_case(session, s.id, cls_case("bad", "negative"))
    assert row.position == 3
    repo.update_case(session, row.id, cls_case("awful", "negative"))
    assert repo.get_case(session, row.id).prompt == "awful"
    repo.delete_case(session, row.id)
    with pytest.raises(repo.NotFound):
        repo.get_case(session, row.id)

    repo.delete_suite(session, s.id)
    assert repo.list_suites(session) == []


def test_suite_name_conflict(session):
    mk_suite(session, "a")
    with pytest.raises(repo.Conflict):
        mk_suite(session, "a")


def test_duplicate_suite_copies_cases_with_unique_names(session):
    s = mk_suite(session, "orig")
    d1 = repo.duplicate_suite(session, s.id)
    d2 = repo.duplicate_suite(session, s.id)
    assert d1.name == "orig (copy)" and d2.name == "orig (copy 2)"
    assert [c.prompt for c in d1.cases] == [c.prompt for c in s.cases]
    assert d1.id != s.id and d1.cases[0].id != s.cases[0].id


def test_run_case_freezes_content_when_source_edited_or_deleted(session):
    s = mk_suite(session)
    src = s.cases[0]
    snap = repo.get_or_create_snapshot(
        session, ModelInfo(name="m:1", digest="d1", parameter_size="8B", quantization="Q4", family="f")
    )
    run = repo.create_run(
        session,
        name="r",
        config={"temperature": 0},
        judge_model=None,
        snapshots=[snap],
        cases=[CaseSource(CaseIn.from_row(src), src.id)],
    )
    repo.update_case(session, src.id, cls_case("CHANGED", "negative"))
    repo.delete_case(session, src.id)
    frozen = repo.get_run(session, run.id).cases[0]
    assert frozen.prompt == "great!" and frozen.expected == "positive"
    assert frozen.config == {"labels": ["positive", "negative"]}

    repo.delete_suite(session, s.id)
    assert repo.get_run(session, run.id).cases[0].prompt == "great!"


def test_snapshot_is_reused_per_digest_and_new_digest_creates_new(session):
    a = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d1"))
    b = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d1"))
    c = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d2"))
    assert a.id == b.id != c.id


def test_run_results_and_scores_lifecycle(session):
    snap = repo.get_or_create_snapshot(session, ModelInfo(name="m:1", digest="d1"))
    run = repo.create_run(
        session,
        name="r",
        config={},
        judge_model="j",
        snapshots=[snap],
        cases=[CaseSource(cls_case())],
    )
    assert run.status == "queued" and run.model_ids == [snap.id]
    repo.set_run_status(session, run.id, "running")
    assert repo.get_run(session, run.id).started_at is not None
    res = repo.add_result(
        session,
        run_id=run.id,
        model_snapshot_id=snap.id,
        run_case_id=run.cases[0].id,
        output="positive",
        latency_ms=12.0,
        metrics={"eval_count": 3},
    )
    a1 = repo.create_attempt(session, run.id, "judge-a")
    a2 = repo.create_attempt(session, run.id, "judge-b")
    repo.add_score(session, result_id=res.id, attempt_id=a1.id, kind="auto", value=1.0, outcome="correct")
    repo.add_score(session, result_id=res.id, attempt_id=a2.id, kind="auto", value=0.0, outcome="wrong")
    assert len(repo.list_scores(session, run.id)) == 2
    assert [s.outcome for s in repo.list_scores(session, run.id, a1.id)] == ["correct"]
    assert repo.latest_attempt(session, run.id).id == a2.id
    repo.set_run_status(session, run.id, "completed")
    assert repo.get_run(session, run.id).finished_at is not None
    assert [r.id for r in repo.list_runs(session)] == [run.id]

    repo.delete_run(session, run.id)
    assert repo.list_runs(session) == [] and repo.list_results(session, run.id) == []
