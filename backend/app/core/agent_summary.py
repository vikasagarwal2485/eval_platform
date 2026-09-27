"""Aggregate metrics for the Agents monitoring views (design D10, spec `agent-monitoring`).

Computed in Python over a bounded window, not a pre-aggregation table - single-machine scale (design Goals),
mirroring how cross-model judging's per-judge statistics are computed from stored rows rather than maintained
incrementally.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentTurn, TurnEvaluation, TurnJudgement, utcnow

WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
DEFAULT_ATTENTION_THRESHOLD = 0.5


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def window_since(window: str) -> datetime | None:
    delta = WINDOWS.get(window)
    return utcnow() - delta if delta else None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p * (len(s) - 1))))
    return s[k]


def _bucket_key(dt: datetime, window: str) -> str:
    return dt.strftime("%Y-%m-%d") if window == "7d" else dt.strftime("%Y-%m-%dT%H:00")


def _latest_by_turn(evals: list[TurnEvaluation]) -> dict[int, TurnEvaluation]:
    """`evals` ordered by attempt_no ascending: the last one seen per turn is the current attempt."""
    out: dict[int, TurnEvaluation] = {}
    for e in evals:
        out[e.turn_id] = e
    return out


def build_agent_summary(session: Session, agent: Agent, *, window: str = "24h") -> dict:
    since = window_since(window)
    q = select(AgentTurn).where(AgentTurn.agent_id == agent.id)
    if since is not None:
        q = q.where(AgentTurn.ended_at >= since)
    turns = list(session.scalars(q))

    by_status: dict[str, int] = {}
    latencies: list[float] = []
    prompt_tokens = completion_tokens = 0
    for t in turns:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        if t.latency_ms is not None:
            latencies.append(t.latency_ms)
        prompt_tokens += t.prompt_tokens or 0
        completion_tokens += t.completion_tokens or 0

    ok_ids = [t.id for t in turns if t.status == "ok"]
    evals: list[TurnEvaluation] = []
    if ok_ids:
        evals = list(
            session.scalars(
                select(TurnEvaluation).where(TurnEvaluation.turn_id.in_(ok_ids)).order_by(TurnEvaluation.attempt_no)
            )
        )
    latest = _latest_by_turn(evals)

    threshold = float((agent.eval_config or {}).get("attention_threshold", DEFAULT_ATTENTION_THRESHOLD))
    scored = [e for e in latest.values() if e.status == "done" and e.value is not None]
    below = [e for e in scored if e.value < threshold]
    skipped_by_reason: dict[str, int] = {}
    pending = 0
    for e in latest.values():
        if e.status == "skipped":
            reason = e.skip_reason or "unknown"
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
        elif e.status in ("pending", "running"):
            pending += 1

    judge_stats: dict[str, dict] = {}
    if latest:
        judgements = session.scalars(
            select(TurnJudgement).where(TurnJudgement.evaluation_id.in_([e.id for e in latest.values()]))
        )
        for j in judgements:
            s = judge_stats.setdefault(j.judge_model, {"values": [], "errors": 0})
            if j.outcome == "judged" and j.value is not None:
                s["values"].append(j.value)
            else:
                s["errors"] += 1
    evaluators = [
        {
            "model": model,
            "mean_score": mean(s["values"]) if s["values"] else None,
            "judged": len(s["values"]),
            "errors": s["errors"],
        }
        for model, s in sorted(judge_stats.items())
    ]

    counts: dict[str, int] = {}
    quality_by_bucket: dict[str, list[float]] = {}
    for t in turns:
        ended = _aware(t.ended_at)
        if ended is None:
            continue
        key = _bucket_key(ended, window)
        counts[key] = counts.get(key, 0) + 1
        e = latest.get(t.id)
        if e and e.status == "done" and e.value is not None:
            quality_by_bucket.setdefault(key, []).append(e.value)
    series = [
        {"bucket": k, "count": counts[k], "quality_mean": mean(v) if (v := quality_by_bucket.get(k)) else None}
        for k in sorted(counts)
    ]

    total = len(turns)
    return {
        "window": window,
        "turns": {"total": total, **by_status},
        "quality": {
            "mean": mean([e.value for e in scored]) if scored else None,
            "evaluated": len(scored),
            "below_threshold": len(below),
            "threshold": threshold,
        },
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "error_rate": (by_status.get("error", 0) / total) if total else None,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "evaluators": evaluators,
        "backlog": {"pending": pending, "skipped": skipped_by_reason},
        "series": series,
    }


def list_needs_attention(session: Session, agent: Agent, *, window: str = "24h", limit: int = 20) -> list[dict]:
    since = window_since(window)
    threshold = float((agent.eval_config or {}).get("attention_threshold", DEFAULT_ATTENTION_THRESHOLD))
    q = select(AgentTurn).where(AgentTurn.agent_id == agent.id, AgentTurn.status == "ok")
    if since is not None:
        q = q.where(AgentTurn.ended_at >= since)
    turns = {t.id: t for t in session.scalars(q)}
    if not turns:
        return []
    evals = list(
        session.scalars(
            select(TurnEvaluation).where(TurnEvaluation.turn_id.in_(turns.keys())).order_by(TurnEvaluation.attempt_no)
        )
    )
    latest = _latest_by_turn(evals)
    out = [
        {
            "turn_id": e.turn_id,
            "value": e.value,
            "input": turns[e.turn_id].input,
            "output": turns[e.turn_id].output,
            "ended_at": (t.ended_at.isoformat() if (t := turns[e.turn_id]).ended_at else None),
        }
        for e in latest.values()
        if e.status == "done" and e.value is not None and e.value < threshold
    ]
    out.sort(key=lambda r: r["value"])
    return out[:limit]
