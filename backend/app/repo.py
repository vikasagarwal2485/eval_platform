"""Persistence helpers. Plain functions over a SQLAlchemy Session."""

from __future__ import annotations

import random as _random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.eligibility import same_model
from app.core.tokens import display_prefix, generate_token, hash_token, verify_token
from app.models import (
    Agent,
    AgentSession,
    AgentSpan,
    AgentTurn,
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
    TurnEvaluation,
    TurnJudgement,
    utcnow,
)
from app.providers.refs import is_cloud_ref, parse_ref
from app.schemas import AgentSettingsUpdate, CaseIn, EvalConfigIn, ModelInfo, SuiteIn


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class AckRequired(ValueError):
    """Raised when saving evaluator settings would send an agent's live traffic to a provider that has not been
    acknowledged for this agent yet (spec `agent-registry`: data-sharing acknowledgment)."""

    def __init__(self, provider: str):
        super().__init__(
            f"Evaluating with '{provider}' sends this agent's live conversations to it; "
            "acknowledge data sharing for this agent and provider first."
        )
        self.provider = provider


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite round-trips a `DateTime(timezone=True)` column as naive UTC; treat it as UTC before comparing
    against `utcnow()` (aware), rather than assuming every read happens in the same session that wrote it."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


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


# ------------------------------------------------------------------ agents (design D4, D5, D11)
def _check_no_self_evaluator(declared_model: str, evaluators: list[str]) -> None:
    for e in evaluators:
        if same_model(e, declared_model):
            raise ValueError(f"'{e}' cannot evaluate this agent: it is the agent's own declared model")


def _merge_acks(existing: dict, new_provider_names: list[str]) -> dict:
    out = dict(existing or {})
    now = utcnow().isoformat()
    for p in new_provider_names:
        out[p] = now
    return out


def _check_provider_acks(evaluators: list[str], acks: dict) -> None:
    for e in evaluators:
        if is_cloud_ref(e):
            provider = parse_ref(e).provider
            if provider not in acks:
                raise AckRequired(provider)


def create_agent(
    session: Session,
    *,
    name: str,
    kind: str,
    declared_model: str,
    eval_config: EvalConfigIn,
    rubric: list[dict] | None,
    provider_acks: list[str] | None = None,
) -> tuple[Agent, str]:
    """Returns (agent, raw_token). The raw token is generated here and never stored - only its hash is kept."""
    if session.scalar(select(Agent).where(Agent.name == name)):
        raise Conflict(f"An agent named '{name}' already exists")
    _check_no_self_evaluator(declared_model, eval_config.evaluators)
    acks = _merge_acks({}, provider_acks or [])
    _check_provider_acks(eval_config.evaluators, acks)
    raw = generate_token()
    agent = Agent(
        name=name,
        kind=kind,
        declared_model=declared_model,
        status="active",
        token_hash=hash_token(raw),
        token_prefix=display_prefix(raw),
        eval_config=eval_config.model_dump(),
        rubric=rubric,
        provider_acks=acks,
    )
    session.add(agent)
    session.flush()
    return agent, raw


def get_agent(session: Session, agent_id: int) -> Agent:
    a = session.get(Agent, agent_id)
    if not a:
        raise NotFound(f"agent {agent_id} not found")
    return a


def get_agent_by_name(session: Session, name: str) -> Agent | None:
    return session.scalar(select(Agent).where(Agent.name == name))


def list_agents(session: Session) -> list[Agent]:
    return list(session.scalars(select(Agent).order_by(Agent.name)))


def update_agent_settings(session: Session, agent_id: int, body: AgentSettingsUpdate) -> Agent:
    agent = get_agent(session, agent_id)
    declared = body.declared_model if body.declared_model is not None else agent.declared_model
    eval_cfg = body.eval_config.model_dump() if body.eval_config is not None else dict(agent.eval_config or {})
    evaluators = eval_cfg.get("evaluators", [])
    _check_no_self_evaluator(declared, evaluators)
    acks = _merge_acks(agent.provider_acks or {}, body.provider_acks)
    _check_provider_acks(evaluators, acks)
    agent.declared_model = declared
    agent.eval_config = eval_cfg
    agent.provider_acks = acks
    if body.clear_rubric:
        agent.rubric = None
    elif body.rubric is not None:
        agent.rubric = [c.model_dump() for c in body.rubric]
    session.flush()
    return agent


def set_agent_status(session: Session, agent_id: int, status: str) -> Agent:
    if status not in ("active", "paused"):
        raise ValueError(f"Unknown agent status '{status}'.")
    agent = get_agent(session, agent_id)
    agent.status = status
    session.flush()
    return agent


def rotate_agent_token(session: Session, agent_id: int) -> tuple[Agent, str]:
    agent = get_agent(session, agent_id)
    raw = generate_token()
    agent.token_hash = hash_token(raw)
    agent.token_prefix = display_prefix(raw)
    session.flush()
    return agent, raw


def verify_agent_token(session: Session, raw_token: str | None) -> Agent | None:
    """Constant-time verification against every agent sharing the token's display prefix (design D11)."""
    if not raw_token:
        return None
    prefix = display_prefix(raw_token)
    for candidate in session.scalars(select(Agent).where(Agent.token_prefix == prefix)):
        if verify_token(raw_token, candidate.token_hash):
            return candidate
    return None


def touch_agent_liveness(session: Session, agent: Agent) -> None:
    agent.last_seen_at = utcnow()
    session.flush()


def delete_agent(session: Session, agent_id: int) -> None:
    session.delete(get_agent(session, agent_id))  # cascades to sessions/turns/spans/evaluations/judgements
    session.flush()


# ------------------------------------------------------------------ trace ingestion (design D2, spec `trace-ingestion`)
def get_or_create_agent_session(session: Session, agent: Agent, external_id: str) -> AgentSession:
    row = session.scalar(
        select(AgentSession).where(AgentSession.agent_id == agent.id, AgentSession.external_id == external_id)
    )
    now = utcnow()
    if row:
        row.last_event_at = now
        session.flush()
        return row
    row = AgentSession(agent_id=agent.id, external_id=external_id, started_at=now, last_event_at=now)
    session.add(row)
    session.flush()
    return row


def get_or_create_turn(session: Session, agent: Agent, sess: AgentSession, external_id: str) -> AgentTurn:
    row = session.scalar(
        select(AgentTurn).where(AgentTurn.agent_id == agent.id, AgentTurn.external_id == external_id)
    )
    if row:
        return row
    seq = (session.scalar(select(func.max(AgentTurn.seq)).where(AgentTurn.session_id == sess.id)) or -1) + 1
    row = AgentTurn(agent_id=agent.id, session_id=sess.id, external_id=external_id, seq=seq, models=[], status="open")
    session.add(row)
    session.flush()
    return row


def get_turn(session: Session, turn_id: int) -> AgentTurn:
    t = session.get(AgentTurn, turn_id)
    if not t:
        raise NotFound(f"turn {turn_id} not found")
    return t


def list_turns(
    session: Session, agent_id: int, *, session_external_id: str | None = None, status: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list[AgentTurn]:
    q = select(AgentTurn).where(AgentTurn.agent_id == agent_id)
    if status:
        q = q.where(AgentTurn.status == status)
    if session_external_id:
        sess = session.scalar(
            select(AgentSession).where(
                AgentSession.agent_id == agent_id, AgentSession.external_id == session_external_id
            )
        )
        q = q.where(AgentTurn.session_id == (sess.id if sess else -1))
    q = q.order_by(AgentTurn.id.desc()).offset(offset).limit(limit)
    return list(session.scalars(q))


def _parse_event_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def apply_turn_start(session: Session, turn: AgentTurn, event, *, was_truncated: bool = False) -> bool:
    """Returns True if the turn already had its start applied (a duplicate, safely ignored)."""
    duplicate = turn.started_at is not None
    if not duplicate:
        turn.input = event.input
        turn.reference = event.reference
        turn.started_at = _parse_event_ts(event.ts) or turn.created_at
        turn.truncated = turn.truncated or was_truncated
    session.flush()
    return duplicate


def apply_span(session: Session, turn: AgentTurn, event, *, was_truncated: bool = False) -> bool:
    """Returns True if a span with this id was already recorded on this turn (a duplicate)."""
    existing = session.scalar(
        select(AgentSpan).where(AgentSpan.turn_id == turn.id, AgentSpan.external_id == event.span_id)
    )
    if existing:
        return True
    started, ended = _parse_event_ts(event.started_at), _parse_event_ts(event.ended_at)
    span = AgentSpan(
        turn_id=turn.id,
        external_id=event.span_id,
        kind=event.kind,
        model=event.model,
        name=event.name,
        input={"messages": event.messages, "args": event.args},
        output=event.output or event.result or "",
        thinking=event.thinking,
        error=event.error,
        started_at=started,
        ended_at=ended,
        latency_ms=(ended - started).total_seconds() * 1000 if started and ended else None,
        ttft_ms=event.ttft_ms,
        prompt_tokens=event.usage.prompt_tokens if event.usage else None,
        completion_tokens=event.usage.completion_tokens if event.usage else None,
    )
    turn.spans.append(span)  # not session.add: keeps the already-loaded `turn.spans` collection in sync
    turn.truncated = turn.truncated or was_truncated
    if event.kind == "llm":
        if event.model:
            if event.model not in (turn.models or []):
                turn.models = [*(turn.models or []), event.model]
        else:
            turn.models_unknown = True
    session.flush()
    return False


def apply_turn_end(session: Session, turn: AgentTurn, event, *, was_truncated: bool = False) -> bool:
    """Returns True if the turn was already closed (a duplicate, safely ignored)."""
    duplicate = turn.status != "open"
    if not duplicate:
        turn.status = event.status
        turn.output = event.output
        turn.error = event.error
        turn.ended_at = _parse_event_ts(event.ts) or utcnow()
        turn.truncated = turn.truncated or was_truncated
        if turn.started_at:
            # `turn.started_at` may have been loaded fresh from SQLite in *this* request (naive) while
            # `turn.ended_at` was just parsed from the event's own ISO string (aware) - normalize both before
            # subtracting, or a turn whose start and end arrive in separate ingest requests (the normal case for
            # a real agent, since turn.start is sent immediately and turn.end only after the LLM responds)
            # raises `TypeError: can't subtract offset-naive and offset-aware datetimes` here and the whole
            # batch 500s, silently dropping the span and turn.end (design.md D-context `_aware`).
            turn.latency_ms = max((_aware(turn.ended_at) - _aware(turn.started_at)).total_seconds() * 1000, 0.0)
        turn.prompt_tokens = sum(s.prompt_tokens or 0 for s in turn.spans) or None
        turn.completion_tokens = sum(s.completion_tokens or 0 for s in turn.spans) or None
    session.flush()
    return duplicate


def sweep_abandoned_turns(session: Session, *, default_abandon_after_s: float = 600.0) -> list[AgentTurn]:
    """Marks open turns past their agent's abandonment timeout as abandoned (spec `trace-ingestion`)."""
    now = utcnow()
    abandoned: list[AgentTurn] = []
    for t in session.scalars(select(AgentTurn).where(AgentTurn.status == "open")):
        timeout = float((t.agent.eval_config or {}).get("abandon_after_s") or default_abandon_after_s)
        started = _aware(t.started_at) or _aware(t.created_at)
        if now - started > timedelta(seconds=timeout):
            t.status = "abandoned"
            t.ended_at = now
            abandoned.append(t)
    if abandoned:
        session.flush()
    return abandoned


# ------------------------------------------------------------------ turn evaluations (design D5-D8)
def latest_evaluation_attempt_no(session: Session, turn_id: int) -> int:
    return session.scalar(select(func.max(TurnEvaluation.attempt_no)).where(TurnEvaluation.turn_id == turn_id)) or 0


def _reference_result(turn: AgentTurn) -> dict | None:
    """A deterministic text-match against the turn's reported expected answer, if it gave one. Needs no model,
    so it is computed immediately rather than waiting for the evaluator queue (spec `live-evaluation`)."""
    if not turn.reference:
        return None
    from app.core.scoring.reasoning import score_reasoning  # local import: avoids a persistence <-> core cycle

    r = score_reasoning(turn.output or "", turn.reference, comparison="text")
    return {"value": r.value, "outcome": r.outcome, "detail": r.detail}


def create_pending_evaluation(
    session: Session, turn: AgentTurn, *, rubric: list[dict], evaluators: list[str], attempt_no: int | None = None
) -> TurnEvaluation:
    n = attempt_no if attempt_no is not None else latest_evaluation_attempt_no(session, turn.id) + 1
    ev = TurnEvaluation(
        turn_id=turn.id,
        attempt_no=n,
        status="pending",
        rubric=rubric,
        evaluators=evaluators,
        reference_result=_reference_result(turn),
    )
    session.add(ev)
    session.flush()
    return ev


def maybe_queue_evaluation(
    session: Session, agent: Agent, turn: AgentTurn, *, rng: _random.Random | None = None
) -> TurnEvaluation | None:
    """Applies the agent's sample rate; returns the created pending evaluation, or None if not sampled
    (spec `live-evaluation`: an unsampled turn gets no row and is shown as not sampled)."""
    from app.core.eval_context import resolve_rubric  # local import: avoids a persistence <-> core cycle

    rate = float((agent.eval_config or {}).get("sample_rate", 1.0))
    if rate <= 0:
        return None
    sampled = rate >= 1 or (rng or _random).random() < rate
    if not sampled:
        return None
    evaluators = list((agent.eval_config or {}).get("evaluators", []))
    return create_pending_evaluation(session, turn, rubric=resolve_rubric(agent), evaluators=evaluators)


def get_evaluation(session: Session, evaluation_id: int) -> TurnEvaluation:
    e = session.get(TurnEvaluation, evaluation_id)
    if not e:
        raise NotFound(f"evaluation {evaluation_id} not found")
    return e


def list_pending_evaluations(session: Session, *, limit: int = 50) -> list[TurnEvaluation]:
    q = select(TurnEvaluation).where(TurnEvaluation.status == "pending").order_by(TurnEvaluation.id).limit(limit)
    return list(session.scalars(q))


def agents_with_open_turns(session: Session, agent_ids: list[int]) -> set[int]:
    """Which of `agent_ids` currently have a turn in flight (`turn.start` seen, no `turn.end` yet). This is the
    actual GPU/model-contention risk a quiet period protects against - unlike recent *activity*, which a
    continuously-active agent (the very traffic this feature exists to evaluate) would never clear, silently
    starving it of any evaluation at all."""
    if not agent_ids:
        return set()
    rows = session.execute(
        select(AgentTurn.agent_id).where(AgentTurn.agent_id.in_(agent_ids), AgentTurn.status == "open").distinct()
    )
    return {r[0] for r in rows}


def list_ready_pending_evaluations(session: Session, *, limit: int = 50, overfetch: int = 4) -> list[TurnEvaluation]:
    """Pending evaluations whose turn has been quiet for at least the agent's configured quiet period, and whose
    agent has no *other* turn actually in flight right now (design D7). Filtered in Python after a bounded fetch -
    fine at the single-machine scale this queue targets (design Goals)."""
    now = utcnow()
    q = select(TurnEvaluation).where(TurnEvaluation.status == "pending").order_by(TurnEvaluation.id).limit(limit * overfetch)
    candidates = list(session.scalars(q))
    busy_agents = agents_with_open_turns(session, [c.turn.agent_id for c in candidates])
    out: list[TurnEvaluation] = []
    for ev in candidates:
        turn = ev.turn
        if turn.ended_at is None:
            continue
        agent = turn.agent
        quiet = timedelta(seconds=float((agent.eval_config or {}).get("quiet_period_s", 20.0)))
        if now - _aware(turn.ended_at) < quiet:
            continue
        if agent.id in busy_agents:
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return out


def apply_evaluation_backlog_cap(session: Session, *, cap: int) -> int:
    """Marks the oldest pending evaluations beyond `cap` as skipped(backlog) rather than letting the queue grow
    without bound (spec `live-evaluation`). Returns how many were skipped."""
    total = session.scalar(select(func.count()).select_from(TurnEvaluation).where(TurnEvaluation.status == "pending"))
    total = total or 0
    if total <= cap:
        return 0
    excess = total - cap
    ids = list(
        session.scalars(
            select(TurnEvaluation.id)
            .where(TurnEvaluation.status == "pending")
            .order_by(TurnEvaluation.id)
            .limit(excess)
        )
    )
    for eid in ids:
        set_evaluation_status(session, eid, "skipped", skip_reason="backlog")
    return len(ids)


def list_prior_turns(session: Session, turn: AgentTurn, *, limit: int) -> list[AgentTurn]:
    """Up to `limit` finished turns of the same session immediately before `turn`, oldest first."""
    if limit <= 0:
        return []
    q = (
        select(AgentTurn)
        .where(
            AgentTurn.session_id == turn.session_id,
            AgentTurn.seq < turn.seq,
            AgentTurn.status.in_(("ok", "error")),
        )
        .order_by(AgentTurn.seq.desc())
        .limit(limit)
    )
    return list(reversed(list(session.scalars(q))))


def reset_running_evaluations(session: Session) -> int:
    """On start-up: an evaluation interrupted mid-run goes back to pending rather than staying stuck."""
    rows = list(session.scalars(select(TurnEvaluation).where(TurnEvaluation.status == "running")))
    for e in rows:
        e.status = "pending"
    if rows:
        session.flush()
    return len(rows)


def set_evaluation_status(
    session: Session, evaluation_id: int, status: str, *, skip_reason: str | None = None
) -> TurnEvaluation:
    e = get_evaluation(session, evaluation_id)
    e.status = status
    if skip_reason is not None:
        e.skip_reason = skip_reason
    if status in ("done", "skipped", "error"):
        e.finished_at = utcnow()
    session.flush()
    return e


def add_turn_judgement(
    session: Session, evaluation_id: int, *, judge_model: str, value: float | None, outcome: str, detail: dict
) -> TurnJudgement:
    j = TurnJudgement(evaluation_id=evaluation_id, judge_model=judge_model, value=value, outcome=outcome, detail=detail)
    session.add(j)
    session.flush()
    return j


def list_turn_judgements(session: Session, evaluation_id: int) -> list[TurnJudgement]:
    return list(
        session.scalars(select(TurnJudgement).where(TurnJudgement.evaluation_id == evaluation_id).order_by(TurnJudgement.id))
    )


def rebuild_evaluation_aggregate(session: Session, evaluation_id: int) -> TurnEvaluation:
    """(Re)compute the turn's aggregate from its stored judgements, reusing `aggregate_judgements` (design D3/D8:
    `TurnJudgement` already carries the `judge_model`/`value`/`outcome`/`detail` shape it expects)."""
    from app.core.scoring.judging import aggregate_judgements  # local import: avoids a persistence <-> core cycle

    e = get_evaluation(session, evaluation_id)
    js = list_turn_judgements(session, evaluation_id)
    if not js:
        return e
    agg = aggregate_judgements(js, kind="turn_eval", mode="panel")
    e.value = agg.value
    e.detail = agg.detail
    e.status = "done" if agg.outcome == "judged" else "error"
    e.finished_at = utcnow()
    session.flush()
    return e


def latest_turn_evaluation(session: Session, turn_id: int) -> TurnEvaluation | None:
    return session.scalar(
        select(TurnEvaluation).where(TurnEvaluation.turn_id == turn_id).order_by(TurnEvaluation.attempt_no.desc()).limit(1)
    )


def list_turn_evaluations(session: Session, turn_id: int) -> list[TurnEvaluation]:
    return list(
        session.scalars(select(TurnEvaluation).where(TurnEvaluation.turn_id == turn_id).order_by(TurnEvaluation.attempt_no))
    )


def reevaluate_turn(
    session: Session, turn: AgentTurn, *, evaluators: list[str] | None = None, rubric: list[dict] | None = None
) -> TurnEvaluation:
    """Queues a new evaluation attempt for one turn (spec `live-evaluation`: re-evaluation keeps history - this
    creates a new, higher `attempt_no` row rather than overwriting the current one)."""
    from app.core.eval_context import resolve_rubric  # local import: avoids a persistence <-> core cycle

    agent = turn.agent
    ev_rubric = rubric if rubric is not None else resolve_rubric(agent)
    ev_evaluators = evaluators if evaluators is not None else list((agent.eval_config or {}).get("evaluators", []))
    return create_pending_evaluation(session, turn, rubric=ev_rubric, evaluators=ev_evaluators)


def reevaluate_agent_turns(
    session: Session,
    agent: Agent,
    *,
    below_score: float | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    evaluators: list[str] | None = None,
    rubric: list[dict] | None = None,
) -> list[TurnEvaluation]:
    """Bulk re-evaluation over a time window and/or a score threshold (spec `live-evaluation`)."""
    q = select(AgentTurn).where(AgentTurn.agent_id == agent.id, AgentTurn.status == "ok")
    if since is not None:
        q = q.where(AgentTurn.ended_at >= since)
    if until is not None:
        q = q.where(AgentTurn.ended_at <= until)
    out: list[TurnEvaluation] = []
    for turn in session.scalars(q):
        if below_score is not None:
            latest = latest_turn_evaluation(session, turn.id)
            if latest is None or latest.value is None or latest.value >= below_score:
                continue
        out.append(reevaluate_turn(session, turn, evaluators=evaluators, rubric=rubric))
    return out
