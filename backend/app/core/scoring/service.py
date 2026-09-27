"""Scoring stage: turns stored results into Score rows. Independent of generation (design D7)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.orm import Session

from app import repo
from app.core.circuits import Circuits
from app.core.scoring.base import ScoreResult
from app.core.scoring.classification import score_classification
from app.core.scoring.constraints import check_constraints
from app.core.scoring.judge import DEFAULT_GENERATION_RUBRIC, REASONING_RUBRIC, JudgeCall, run_judge
from app.core.scoring.judging import JudgeTarget, plan_judgements, rebuild_aggregate
from app.core.scoring.reasoning import score_reasoning
from app.models import Result, RunCase
from app.ollama.client import OllamaClient

PRIMARY_KIND = {"classification": "auto", "reasoning": "auto", "generation": "judge"}


def primary_kind(category: str) -> str:
    return PRIMARY_KIND[category]


def live_scores(case: RunCase, result: Result) -> list[ScoreResult]:
    """Scores that need no model: correctness, constraint checks, and error rows. Pure."""
    cat, cfg = case.category, case.config or {}
    if result.status != "ok":
        # A failed request is a failed answer: counts as 0 and is surfaced as `error` in the UI.
        return [ScoreResult(primary_kind(cat), 0.0, "error", {"error": result.error})]
    if cat == "classification":
        return [score_classification(result.output, cfg.get("labels", []), case.expected)]
    if cat == "reasoning":
        return [score_reasoning(result.output, case.expected, cfg.get("comparison", "text"), cfg.get("tolerance", 0.0))]
    checks = check_constraints(result.output, cfg.get("constraints"))
    return [checks] if checks else []


def store(session: Session, attempt_id: int, result_id: int, s: ScoreResult) -> None:
    repo.add_score(
        session,
        result_id=result_id,
        attempt_id=attempt_id,
        kind=s.kind,
        value=s.value,
        outcome=s.outcome,
        detail=s.detail,
    )


def score_live(session: Session, attempt_id: int, case: RunCase, result: Result) -> list[ScoreResult]:
    scores = live_scores(case, result)
    for s in scores:
        store(session, attempt_id, result.id, s)
    return scores


ProgressCb = Callable[[int, int], Awaitable[None]] | None
CancelCheck = Callable[[], bool]
UnloadCb = Callable[[str], Awaitable[None]] | None


async def judge_run(
    session: Session,
    client: OllamaClient,
    *,
    run_id: int,
    attempt_id: int,
    judge_mode: str,
    judge_model: str | None,
    judge_think: Mapping[str, bool | None],
    judge_reasoning: bool,
    cancelled: CancelCheck = lambda: False,
    on_progress: ProgressCb = None,
    unload: UnloadCb = None,
    circuits: Circuits | None = None,
) -> bool:
    """Judge stage. Runs after all generation so judging never disturbs measured latency.

    Modes: `none` leaves generation answers `unscored`; `single` uses `judge_model` for every answer;
    `cross_model` has each answer judged only by the *other* evaluated models. Work is executed judge by judge
    (each judge is loaded once; the previous one is unloaded first). Every individual judgement is stored as it
    finishes, and the per-answer aggregate rows are (re)built in a `finally`, so a cancel keeps what was judged.
    Returns False if cancelled part-way. Connection loss propagates to the caller.
    """
    run = repo.get_run(session, run_id)
    cases = {c.id: c for c in run.cases}
    snaps = repo.run_snapshots(session, run)
    author_names = {s.id: s.name for s in snaps}
    results = {r.id: r for r in repo.list_results(session, run_id) if r.status == "ok"}  # failed requests: never judged

    targets: list[JudgeTarget] = []
    for r in results.values():
        case = cases[r.run_case_id]
        if case.category == "generation":
            targets.append(JudgeTarget(r.id, r.model_snapshot_id, "judge"))
        elif case.category == "reasoning" and judge_reasoning and judge_mode != "none":
            targets.append(JudgeTarget(r.id, r.model_snapshot_id, "judge_reasoning"))

    if judge_mode == "none":
        for t in targets:
            store(
                session,
                attempt_id,
                t.result_id,
                ScoreResult(t.kind, None, "unscored", {"reason": "no judge model configured"}),
            )
        session.commit()
        return True

    tasks = plan_judgements(judge_mode, judge_model, [(s.id, s.name) for s in snaps], targets)
    done, previous = 0, None
    try:
        for task in tasks:
            if cancelled():
                return False
            if previous is not None and previous != task.judge_model and unload:
                await unload(previous)  # free memory before the next judge loads
            previous = task.judge_model
            r, case = results[task.result_id], cases[results[task.result_id].run_case_id]
            if task.kind == "judge":
                call = JudgeCall(
                    task=case.prompt, response=r.output or "", rubric=case.rubric or DEFAULT_GENERATION_RUBRIC
                )
            else:
                trace = f"{r.thinking}\n\n" if r.thinking else ""
                call = JudgeCall(
                    task=case.prompt, response=f"{trace}{r.output}", rubric=REASONING_RUBRIC, kind="judge_reasoning"
                )
            # cross-model planning never pairs an answer with its author; single mode may (and is then flagged)
            call.extra = {
                "self_judged": judge_mode == "single" and author_names.get(r.model_snapshot_id) == task.judge_model
            }
            if circuits is not None and (why := circuits.blocked(task.judge_model)) is not None:
                # a provider failure earlier in this run closed this judge: record the error without sending
                score, jm = (
                    ScoreResult(
                        task.kind,
                        None,
                        "error",
                        {"error": why, "judge_model": task.judge_model, "attempts": 0, **call.extra},
                    ),
                    [],
                )
            else:
                score, jm = await run_judge(
                    client,
                    task.judge_model,
                    call,
                    think=judge_think.get(task.judge_model),
                    on_error=(lambda exc, m=task.judge_model: circuits.record(m, exc))
                    if circuits is not None
                    else None,
                )
            score.detail["judge_metrics"] = jm  # kept apart from the evaluated model's own metrics
            repo.add_judgement(
                session,
                attempt_id=attempt_id,
                result_id=task.result_id,
                kind=task.kind,
                judge_model=task.judge_model,
                value=score.value,
                outcome=score.outcome,
                detail=score.detail,
            )
            session.commit()
            done += 1
            if on_progress:
                await on_progress(done, len(tasks))
        return True
    finally:
        for t in targets:
            rebuild_aggregate(session, attempt_id=attempt_id, result_id=t.result_id, kind=t.kind, mode=judge_mode)
        session.commit()


async def rescore_run(
    session: Session,
    client: OllamaClient,
    *,
    run_id: int,
    judge_mode: str,
    judge_model: str | None,
    judge_think: Mapping[str, bool | None],
    judge_reasoning: bool = False,
    cancelled: CancelCheck = lambda: False,
    on_progress: ProgressCb = None,
    unload: UnloadCb = None,
    circuits: Circuits | None = None,
) -> int:
    """New scoring attempt over stored outputs. Results and performance metrics are untouched;
    earlier attempts stay readable. Returns the new attempt id."""
    run = repo.get_run(session, run_id)
    cases = {c.id: c for c in run.cases}
    attempt = repo.create_attempt(session, run_id, judge_model, judge_mode)
    session.commit()
    for r in repo.list_results(session, run_id):
        score_live(session, attempt.id, cases[r.run_case_id], r)
    session.commit()
    await judge_run(
        session,
        client,
        run_id=run_id,
        attempt_id=attempt.id,
        judge_mode=judge_mode,
        judge_model=judge_model,
        judge_think=judge_think,
        judge_reasoning=judge_reasoning,
        cancelled=cancelled,
        on_progress=on_progress,
        unload=unload,
        circuits=circuits,
    )
    session.commit()
    return attempt.id
