"""CSV/JSON export of a run: one row per model/case/repeat."""

from __future__ import annotations

import csv
import io

from sqlalchemy.orm import Session

from app import repo
from app.core.model_meta import provider_of
from app.core.scoring.service import primary_kind

COLUMNS = [
    "run_id",
    "judge_mode",
    "model",
    "source",
    "provider",
    "model_version",
    "category",
    "case_id",
    "case_title",
    "repeat",
    "status",
    "outcome",
    "score",
    "constraints",
    "judges",
    "expected",
    "predicted",
    "final_answer",
    "output",
    "error",
    "is_cold",
    "latency_ms",
    "ttft_ms",
    "ttft_answer_ms",
    "tokens_per_s",
    "output_tokens",
    "thinking_tokens",
    "prompt_tokens",
    "load_ms",
    "attempts",
    "params_ignored",
]


def _judge_cell(j: dict) -> str:
    """`model=0.750` for a successful judgement, `model=error` for a failed one."""
    return (
        f"{j['judge_model']}={j['value']:.3f}"
        if j.get("outcome") == "judged" and j.get("value") is not None
        else f"{j['judge_model']}=error"
    )


def export_rows(session: Session, run, attempt_id: int | None = None) -> list[dict]:
    attempt = (
        repo.latest_attempt(session, run.id)
        if attempt_id is None
        else next((a for a in repo.list_attempts(session, run.id) if a.id == attempt_id), None)
    )
    scores: dict[int, dict] = {}
    if attempt:
        for s in repo.list_scores(session, run.id, attempt.id):
            scores.setdefault(s.result_id, {})[s.kind] = s
    cases = {c.id: c for c in run.cases}
    snaps = repo.run_snapshots(session, run)
    names = {s.id: s.name for s in snaps}
    sources = {s.id: s.source for s in snaps}
    rows = []
    for r in repo.list_results(session, run.id):
        case = cases[r.run_case_id]
        sc = scores.get(r.id, {})
        prim = sc.get(primary_kind(case.category))
        cons = sc.get("constraints")
        d = prim.detail if prim else {}
        m = r.metrics or {}
        judgements = d.get("judgements") or []
        rows.append(
            {
                "run_id": run.id,
                "judge_mode": attempt.judge_mode if attempt else "none",
                "model": names[r.model_snapshot_id],
                "source": sources[r.model_snapshot_id],
                "provider": provider_of(names[r.model_snapshot_id]),
                "model_version": m.get("model_version"),
                "attempts": m.get("attempts", 1),
                "params_ignored": ";".join(i["name"] for i in m.get("params_ignored", [])),
                "params_ignored_detail": m.get("params_ignored", []),  # JSON export only
                "category": case.category,
                "case_id": case.id,
                "case_title": case.title,
                "repeat": r.repeat_idx,
                "status": r.status,
                "outcome": prim.outcome if prim else "unscored",
                "score": prim.value if prim else None,
                "constraints": cons.outcome if cons else None,
                "judges": ";".join(_judge_cell(j) for j in judgements),
                "judgements": judgements,  # JSON export only (CSV writes COLUMNS)
                "expected": case.expected,
                "predicted": d.get("predicted"),
                "final_answer": d.get("final_answer"),
                "output": r.output,
                "error": r.error,
                "is_cold": r.is_cold,
                "latency_ms": r.latency_ms,
                "ttft_ms": r.ttft_ms,
                "ttft_answer_ms": m.get("ttft_answer_ms"),
                "tokens_per_s": r.tokens_per_s,
                "output_tokens": r.output_tokens,
                "thinking_tokens": m.get("thinking_tokens"),
                "prompt_tokens": m.get("prompt_tokens"),
                "load_ms": m.get("load_ms"),
            }
        )
    return rows


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({k: ("" if row[k] is None else row[k]) for k in COLUMNS})
    return buf.getvalue()
