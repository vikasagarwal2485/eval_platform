"""Combine individual judgements into the one aggregate score per answer (design D3, D4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app import repo
from app.core.scoring.base import ScoreResult

JUDGE_MODES = ("none", "single", "cross_model")


def resolve_judging(judge_mode: str | None, judge_model: str | None, model_names: list[str]) -> tuple[str, str | None]:
    """Validate a judging request and return the effective (mode, judge_model).

    An omitted mode is inferred from `judge_model` so older clients keep working. Raises ValueError with a
    user-facing message for contradictory or impossible requests (design D1).
    """
    mode = judge_mode or ("single" if judge_model else "none")
    if mode not in JUDGE_MODES:
        raise ValueError(f"Unknown judging mode '{mode}'.")
    if mode == "single" and not judge_model:
        raise ValueError("Single judge mode needs a judge model.")
    if mode == "none" and judge_model:
        raise ValueError("A judge model was given but the judging mode is 'none'.")
    if mode == "cross_model":
        if judge_model:
            raise ValueError("Cross-model judging uses the evaluated models as judges; remove the judge model.")
        if len(set(model_names)) < 2:
            raise ValueError("Cross-model judging needs at least two different models.")
    return mode, judge_model


# detail keys copied from a judgement into its per-judge summary
_SUMMARY_KEYS = ("criteria", "raw_mean", "error", "attempts", "judge_metrics")


def judgement_summary(j: Any) -> dict:
    """API-facing view of one judgement (`j` is a Judgement row or anything with the same attributes)."""
    out = {"judge_model": j.judge_model, "value": j.value, "outcome": j.outcome}
    out.update({k: j.detail[k] for k in _SUMMARY_KEYS if k in (j.detail or {})})
    return out


def aggregate_judgements(judgements: list[Any], *, kind: str, mode: str) -> ScoreResult:
    """One score for an answer from all of its judgements.

    value = arithmetic mean of the successful judgements' normalized scores; outcome is `judged` when at
    least one succeeded, otherwise `error` (the answer is then excluded from category means).
    Single-judge results keep today's flat detail shape (criteria etc. at the top level).
    """
    ok = [j for j in judgements if j.outcome == "judged" and j.value is not None]
    value = sum(j.value for j in ok) / len(ok) if ok else None
    detail: dict = {}
    if mode == "single" and len(judgements) == 1:
        detail.update(judgements[0].detail or {})  # criteria, raw_mean, judge_model, attempts, self_judged, ...
    else:
        detail["self_judged"] = False  # cross-model planning never pairs an answer with its author
        if not ok:
            detail["error"] = (
                "; ".join(f"{j.judge_model}: {(j.detail or {}).get('error', 'failed')}" for j in judgements)
                or "no judgements"
            )
    detail.update({"mode": mode, "judges_used": len(ok), "judgements": [judgement_summary(j) for j in judgements]})
    return ScoreResult(kind, value, "judged" if ok else "error", detail)


def rebuild_aggregate(session: Session, *, attempt_id: int, result_id: int, kind: str, mode: str) -> ScoreResult | None:
    """(Re)write the aggregate score row of one answer from its stored judgements. Returns None if there are none."""
    js = repo.list_judgements(session, attempt_id, result_id)
    js = [j for j in js if j.kind == kind]
    if not js:
        return None
    agg = aggregate_judgements(js, kind=kind, mode=mode)
    repo.replace_score(
        session,
        attempt_id=attempt_id,
        result_id=result_id,
        kind=kind,
        value=agg.value,
        outcome=agg.outcome,
        detail=agg.detail,
    )
    return agg


# ---------------------------------------------------------------- planning (design D2)
@dataclass(frozen=True)
class JudgeTarget:
    """An answer that needs judging."""

    result_id: int
    author_id: int  # ModelSnapshot id of the model that wrote it
    kind: str  # judge | judge_reasoning


@dataclass(frozen=True)
class JudgeTask:
    """One judge call: `judge_model` scores answer `result_id`."""

    result_id: int
    author_id: int
    judge_model: str
    kind: str


def plan_judgements(
    mode: str,
    judge_model: str | None,
    models: list[tuple[int, str]],
    targets: list[JudgeTarget],
) -> list[JudgeTask]:
    """Who judges what, grouped judge-by-judge (each judge's tasks are contiguous).

    `models` is the run's evaluated models as (snapshot id, name) in run order.
      none         -> no tasks (answers stay unscored)
      single       -> `judge_model` judges every target
      cross_model  -> every evaluated model *other than the author* judges each target. Authors are matched
                      by snapshot id, never by display name, so a model can never grade its own answer.
    """
    if mode == "single":
        return [JudgeTask(t.result_id, t.author_id, judge_model, t.kind) for t in targets] if judge_model else []
    if mode != "cross_model":
        return []
    return [
        JudgeTask(t.result_id, t.author_id, name, t.kind)
        for snap_id, name in models
        for t in targets
        if t.author_id != snap_id
    ]
