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
    Provider,
    RegisteredModel,
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
        provider_kind=info.provider_kind,
        source=info.source,
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


# ------------------------------------------------------------------ providers and registered models
def get_provider(session: Session, provider_id: int) -> Provider:
    p = session.get(Provider, provider_id)
    if not p:
        raise NotFound(f"provider {provider_id} not found")
    return p


def get_provider_by_name(session: Session, name: str) -> Provider | None:
    return session.scalar(select(Provider).where(Provider.name == name))


def list_providers(session: Session) -> list[Provider]:
    return list(session.scalars(select(Provider).order_by(Provider.name)))


def create_provider(
    session: Session, *, kind: str, name: str, key_env: str, base_url: str | None, ack_at: datetime | None
) -> Provider:
    if get_provider_by_name(session, name):
        raise Conflict(f"A provider named '{name}' already exists")
    p = Provider(kind=kind, name=name, key_env=key_env, base_url=base_url, ack_at=ack_at)
    session.add(p)
    session.flush()
    return p


def update_provider(
    session: Session,
    provider_id: int,
    *,
    key_env: str | None = None,
    base_url: str | None = None,
    clear_base_url: bool = False,
) -> Provider:
    """Change the key variable name or base URL. The name is part of every model reference and never changes."""
    p = get_provider(session, provider_id)
    if key_env is not None:
        p.key_env = key_env
    if clear_base_url:
        p.base_url = None
    elif base_url is not None:
        p.base_url = base_url
    session.flush()
    return p


def provider_in_use(session: Session, name: str) -> bool:
    """True if a queued or running run uses one of the provider's models, as contestant or judge."""
    prefix = f"@{name}/"
    for run in session.scalars(select(Run).where(Run.status.in_(("queued", "running")))):
        refs = [s.name for s in run_snapshots(session, run)] + ([run.judge_model] if run.judge_model else [])
        if any(r.startswith(prefix) for r in refs):
            return True
    return False


def delete_provider(session: Session, provider_id: int) -> None:
    p = get_provider(session, provider_id)
    if provider_in_use(session, p.name):
        raise Conflict(f"Provider '{p.name}' is used by a queued or running run; let it finish or cancel it first")
    session.delete(p)  # its registered models go with it; past runs keep their snapshots
    session.flush()


def add_registered_model(
    session: Session,
    provider_id: int,
    model_id: str,
    *,
    display_name: str = "",
    enabled: bool = True,
    reasoning: bool = False,
) -> RegisteredModel:
    p = get_provider(session, provider_id)
    if session.scalar(
        select(RegisteredModel).where(RegisteredModel.provider_id == p.id, RegisteredModel.model_id == model_id)
    ):
        raise Conflict(f"'{model_id}' is already registered under provider '{p.name}'")
    m = RegisteredModel(
        provider_id=p.id, model_id=model_id, display_name=display_name, enabled=enabled, reasoning=reasoning
    )
    session.add(m)
    session.flush()
    return m


def get_registered_model(session: Session, model_pk: int) -> RegisteredModel:
    m = session.get(RegisteredModel, model_pk)
    if not m:
        raise NotFound(f"model {model_pk} not found")
    return m


def update_registered_model(
    session: Session,
    model_pk: int,
    *,
    enabled: bool | None = None,
    reasoning: bool | None = None,
    display_name: str | None = None,
) -> RegisteredModel:
    m = get_registered_model(session, model_pk)
    if enabled is not None:
        m.enabled = enabled
    if reasoning is not None:
        m.reasoning = reasoning
    if display_name is not None:
        m.display_name = display_name
    session.flush()
    return m


def delete_registered_model(session: Session, model_pk: int) -> None:
    session.delete(get_registered_model(session, model_pk))
    session.flush()


def list_registered_models(session: Session, *, enabled_only: bool = False) -> list[RegisteredModel]:
    q = select(RegisteredModel).join(Provider, Provider.id == RegisteredModel.provider_id)
    if enabled_only:
        q = q.where(RegisteredModel.enabled.is_(True))
    return list(session.scalars(q.order_by(Provider.name, RegisteredModel.id)))


def find_registered(
    session: Session, provider_name: str, model_id: str
) -> tuple[Provider | None, RegisteredModel | None]:
    p = get_provider_by_name(session, provider_name)
    if not p:
        return None, None
    m = session.scalar(
        select(RegisteredModel).where(RegisteredModel.provider_id == p.id, RegisteredModel.model_id == model_id)
    )
    return p, m
