"""Persistence helpers. Plain functions over a SQLAlchemy Session."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Judgement,
    ModelSnapshot,
    Result,
    Run,
    RunCase,
    Score,
    ScoringAttempt,
    Suite,
    TestCase,
    utcnow,
)
from app.schemas import CaseIn, ModelInfo, SuiteIn


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def default_judge_mode(judge_model: str | None) -> str:
    """Mode implied by the legacy single `judge_model` field."""
    return "single" if judge_model else "none"


# ------------------------------------------------------------------ suites / cases
def _apply_case(row: TestCase, case: CaseIn) -> None:
    row.category = case.category
    row.title = case.title
    row.prompt = case.prompt
    row.system_prompt = case.system_prompt
    row.expected = case.expected
    row.config = case.to_config()
    row.rubric = case.to_rubric()
    row.tags = list(case.tags)


def create_suite(session: Session, data: SuiteIn, *, is_builtin: bool = False) -> Suite:
    if session.scalar(select(Suite).where(Suite.name == data.name)):
        raise Conflict(f"A suite named '{data.name}' already exists")
    suite = Suite(name=data.name, description=data.description, is_builtin=is_builtin)
    for i, c in enumerate(data.cases):
        row = TestCase(position=i)
        _apply_case(row, c)
        suite.cases.append(row)
    session.add(suite)
    session.flush()
    return suite


def get_suite(session: Session, suite_id: int) -> Suite:
    suite = session.get(Suite, suite_id)
    if not suite:
        raise NotFound(f"suite {suite_id} not found")
    return suite


def list_suites(session: Session) -> list[Suite]:
    return list(session.scalars(select(Suite).order_by(Suite.is_builtin.desc(), Suite.name)))


def update_suite(session: Session, suite_id: int, *, name: str | None, description: str | None) -> Suite:
    suite = get_suite(session, suite_id)
    if name is not None and name != suite.name:
        if session.scalar(select(Suite).where(Suite.name == name, Suite.id != suite_id)):
            raise Conflict(f"A suite named '{name}' already exists")
        suite.name = name
    if description is not None:
        suite.description = description
    session.flush()
    return suite


def delete_suite(session: Session, suite_id: int) -> None:
    session.delete(get_suite(session, suite_id))
    session.flush()


def duplicate_suite(session: Session, suite_id: int) -> Suite:
    src = get_suite(session, suite_id)
    existing = {n for (n,) in session.execute(select(Suite.name))}
    name, n = f"{src.name} (copy)", 2
    while name in existing:
        name, n = f"{src.name} (copy {n})", n + 1
    data = SuiteIn(name=name, description=src.description, cases=[CaseIn.from_row(c) for c in src.cases])
    return create_suite(session, data)


def add_case(session: Session, suite_id: int, case: CaseIn) -> TestCase:
    suite = get_suite(session, suite_id)
    pos = (session.scalar(select(func.max(TestCase.position)).where(TestCase.suite_id == suite_id)) or -1) + 1
    row = TestCase(suite_id=suite.id, position=pos)
    _apply_case(row, case)
    session.add(row)
    session.flush()
    return row


def get_case(session: Session, case_id: int) -> TestCase:
    row = session.get(TestCase, case_id)
    if not row:
        raise NotFound(f"case {case_id} not found")
    return row


def update_case(session: Session, case_id: int, case: CaseIn) -> TestCase:
    row = get_case(session, case_id)
    _apply_case(row, case)
    session.flush()
    return row


def delete_case(session: Session, case_id: int) -> None:
    row = get_case(session, case_id)
    suite = row.suite
    session.delete(row)
    session.flush()
    session.expire(suite, ["cases"])


def suite_counts(suite: Suite) -> dict[str, int]:
    return dict(Counter(c.category for c in suite.cases))


# ------------------------------------------------------------------ model snapshots
def get_or_create_snapshot(session: Session, info: ModelInfo) -> ModelSnapshot:
    snap = session.scalar(
        select(ModelSnapshot).where(ModelSnapshot.name == info.name, ModelSnapshot.digest == info.digest)
    )
    if snap:
        return snap
    snap = ModelSnapshot(
        name=info.name,
        digest=info.digest,
        parameter_size=info.parameter_size,
        quantization=info.quantization,
        family=info.family,
        size_bytes=info.size_bytes,
        capabilities=list(info.capabilities),
    )
    session.add(snap)
    session.flush()
    return snap


# ------------------------------------------------------------------ runs
@dataclass
class CaseSource:
    """A case to freeze into a run: authored content plus optional source id."""

    case: CaseIn
    source_case_id: int | None = None


def create_run(
    session: Session,
    *,
    name: str,
    config: dict,
    judge_model: str | None,
    snapshots: list[ModelSnapshot],
    cases: list[CaseSource],
    parent_run_id: int | None = None,
    ollama_version: str | None = None,
    judge_mode: str | None = None,
) -> Run:
    run = Run(
        name=name,
        config=config,
        judge_model=judge_model,
        judge_mode=judge_mode or default_judge_mode(judge_model),
        model_ids=[s.id for s in snapshots],
        parent_run_id=parent_run_id,
        ollama_version=ollama_version,
        status="queued",
    )
    for i, cs in enumerate(cases):
        c = cs.case
        run.cases.append(
            RunCase(
                source_case_id=cs.source_case_id,
                position=i,
                category=c.category,
                title=c.title,
                prompt=c.prompt,
                system_prompt=c.system_prompt,
                expected=c.expected,
                config=c.to_config(),
                rubric=c.to_rubric(),
            )
        )
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if not run:
        raise NotFound(f"run {run_id} not found")
    return run


def list_runs(session: Session) -> list[Run]:
    return list(session.scalars(select(Run).order_by(Run.id.desc())))


def delete_run(session: Session, run_id: int) -> None:
    run = get_run(session, run_id)
    session.query(Result).filter(Result.run_id == run_id).delete()
    session.query(ScoringAttempt).filter(ScoringAttempt.run_id == run_id).delete()
    session.delete(run)
    session.flush()


def set_run_status(session: Session, run_id: int, status: str, *, error: str | None = None) -> Run:
    run = get_run(session, run_id)
    run.status = status
    if error is not None:
        run.error = error
    now: datetime = utcnow()
    if status == "running" and run.started_at is None:
        run.started_at = now
    if status in ("completed", "cancelled", "failed"):
        run.finished_at = now
    session.flush()
    return run


def run_snapshots(session: Session, run: Run) -> list[ModelSnapshot]:
    by_id = {s.id: s for s in session.scalars(select(ModelSnapshot).where(ModelSnapshot.id.in_(run.model_ids)))}
    return [by_id[i] for i in run.model_ids if i in by_id]


# ------------------------------------------------------------------ results / scores
def add_result(session: Session, **fields) -> Result:
    result = Result(**fields)
    session.add(result)
    session.flush()
    return result


def list_results(session: Session, run_id: int) -> list[Result]:
    return list(session.scalars(select(Result).where(Result.run_id == run_id).order_by(Result.id)))


def create_attempt(
    session: Session, run_id: int, judge_model: str | None, judge_mode: str | None = None
) -> ScoringAttempt:
    att = ScoringAttempt(
        run_id=run_id, judge_model=judge_model, judge_mode=judge_mode or default_judge_mode(judge_model)
    )
    session.add(att)
    session.flush()
    return att


def list_attempts(session: Session, run_id: int) -> list[ScoringAttempt]:
    return list(
        session.scalars(select(ScoringAttempt).where(ScoringAttempt.run_id == run_id).order_by(ScoringAttempt.id))
    )


def latest_attempt(session: Session, run_id: int) -> ScoringAttempt | None:
    return session.scalar(
        select(ScoringAttempt).where(ScoringAttempt.run_id == run_id).order_by(ScoringAttempt.id.desc()).limit(1)
    )


def add_score(session: Session, **fields) -> Score:
    score = Score(**fields)
    session.add(score)
    session.flush()
    return score


def list_scores(session: Session, run_id: int, attempt_id: int | None = None) -> list[Score]:
    q = select(Score).join(Result, Score.result_id == Result.id).where(Result.run_id == run_id)
    if attempt_id is not None:
        q = q.where(Score.attempt_id == attempt_id)
    return list(session.scalars(q.order_by(Score.id)))


def add_judgement(session: Session, **fields) -> Judgement:
    j = Judgement(**fields)
    session.add(j)
    session.flush()
    return j


def list_judgements(session: Session, attempt_id: int, result_id: int | None = None) -> list[Judgement]:
    q = select(Judgement).where(Judgement.attempt_id == attempt_id)
    if result_id is not None:
        q = q.where(Judgement.result_id == result_id)
    return list(session.scalars(q.order_by(Judgement.id)))


def replace_score(
    session: Session, *, attempt_id: int, result_id: int, kind: str, value: float | None, outcome: str, detail: dict
) -> Score:
    """Write the single score row for (attempt, result, kind), replacing any earlier one (idempotent)."""
    session.query(Score).filter(
        Score.attempt_id == attempt_id, Score.result_id == result_id, Score.kind == kind
    ).delete()
    return add_score(
        session, attempt_id=attempt_id, result_id=result_id, kind=kind, value=value, outcome=outcome, detail=detail
    )
