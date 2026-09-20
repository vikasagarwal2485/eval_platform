"""Leaderboard/summary for a run, computed on demand from stored rows (design D9)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app import repo
from app.core.metrics import perf_stats
from app.core.scoring.aggregate import DEFAULT_WEIGHTS, ScoredItem, category_scores, composite_score
from app.core.scoring.classification import classification_metrics
from app.core.scoring.service import primary_kind
from app.schemas import CATEGORIES


def parse_weights(text: str | None) -> dict[str, float]:
    """'classification:0.4,reasoning:0.4,generation:0.2' -> dict. Raises ValueError on bad input."""
    if not text:
        return dict(DEFAULT_WEIGHTS)
    out = dict.fromkeys(CATEGORIES, 0.0)
    for part in text.split(","):
        key, _, val = part.partition(":")
        key = key.strip()
        if key not in out:
            raise ValueError(f"unknown category '{key}'")
        try:
            w = float(val)
        except ValueError as exc:
            raise ValueError(f"invalid weight for '{key}'") from exc
        if w < 0:
            raise ValueError("weights must be non-negative")
        out[key] = w
    if sum(out.values()) <= 0:
        raise ValueError("at least one weight must be positive")
    return out


def judging_summary(session: Session, attempt) -> dict:
    """Mode and per-judge statistics for one scoring attempt (from the stored individual judgements).

    Judges in cross-model mode score different answers, so their averages are only a rough strictness check.
    """
    if attempt is None:
        return {"mode": "none", "judges": []}
    stats: dict[str, dict] = {}
    for j in repo.list_judgements(session, attempt.id):
        st = stats.setdefault(
            j.judge_model,
            {"model": j.judge_model, "judged": 0, "errors": 0, "_gen": [], "_reasoning": []},
        )
        if j.outcome == "judged" and j.value is not None:
            st["judged"] += 1
            st["_reasoning" if j.kind == "judge_reasoning" else "_gen"].append(j.value)
        else:
            st["errors"] += 1
    judges = []
    for st in stats.values():
        gen, rea = st.pop("_gen"), st.pop("_reasoning")
        st["mean_score"] = sum(gen) / len(gen) if gen else None
        st["reasoning_mean_score"] = sum(rea) / len(rea) if rea else None
        judges.append(st)
    return {"mode": attempt.judge_mode, "judges": judges}


def build_summary(
    session: Session,
    run,
    *,
    attempt_id: int | None = None,
    weights: dict[str, float] | None = None,
    include_cold: bool = False,
) -> dict:
    weights = weights or dict(DEFAULT_WEIGHTS)
    attempt = (
        next((a for a in repo.list_attempts(session, run.id) if a.id == attempt_id), None)
        if attempt_id
        else repo.latest_attempt(session, run.id)
    )
    scores_by_result: dict[int, dict[str, object]] = defaultdict(dict)
    if attempt:
        for s in repo.list_scores(session, run.id, attempt.id):
            scores_by_result[s.result_id][s.kind] = s

    cases = {c.id: c for c in run.cases}
    results = repo.list_results(session, run.id)
    snaps = repo.run_snapshots(session, run)
    by_model: dict[int, list] = defaultdict(list)
    for r in results:
        by_model[r.model_snapshot_id].append(r)

    rows = []
    for snap in snaps:
        mrs = by_model.get(snap.id, [])
        items, cls_pairs, cons_pass, cons_total, self_judged, judges_per_answer = [], [], 0, 0, False, None
        for r in mrs:
            case = cases[r.run_case_id]
            sc = scores_by_result.get(r.id, {})
            prim = sc.get(primary_kind(case.category))
            items.append(
                ScoredItem(
                    snap.id, case.id, case.category, prim.value if prim else None, prim.outcome if prim else "unscored"
                )
            )
            if case.category == "classification" and prim and case.expected is not None and r.status == "ok":
                cls_pairs.append((prim.detail.get("expected") or case.expected, prim.detail.get("predicted")))
            cons = sc.get("constraints")
            if cons:
                cons_total += 1
                cons_pass += cons.outcome == "pass"
            if prim and prim.detail.get("self_judged"):
                self_judged = True
            if prim and prim.detail.get("judgements"):
                judges_per_answer = max(judges_per_answer or 0, len(prim.detail["judgements"]))
        cats = category_scores(items).get(snap.id, {})
        perf_by_cat = {
            cat: perf_stats([r for r in mrs if cases[r.run_case_id].category == cat], include_cold=include_cold)
            for cat in CATEGORIES
            if any(cases[r.run_case_id].category == cat for r in mrs)
        }
        rows.append(
            {
                "model": snap.name,
                "model_id": snap.id,
                "digest": snap.digest,
                "parameter_size": snap.parameter_size,
                "quantization": snap.quantization,
                "categories": cats,
                "composite": composite_score(cats, weights),
                "performance": perf_stats(mrs, include_cold=include_cold),
                "performance_by_category": perf_by_cat,
                "memory": run.footprints.get(str(snap.id)),
                "classification": classification_metrics(cls_pairs) if cls_pairs else None,
                "constraints": {"passed": cons_pass, "total": cons_total} if cons_total else None,
                "self_judged": self_judged,
                "judges_per_answer": judges_per_answer,
                "errors": sum(1 for r in mrs if r.status != "ok"),
            }
        )
    return {
        "run_id": run.id,
        "status": run.status,
        "weights": weights,
        "include_cold": include_cold,
        "attempt": (
            {"id": attempt.id, "judge_model": attempt.judge_model, "judge_mode": attempt.judge_mode}
            if attempt
            else None
        ),
        "attempts": [
            {
                "id": a.id,
                "judge_model": a.judge_model,
                "judge_mode": a.judge_mode,
                "created_at": a.created_at.isoformat(),
            }
            for a in repo.list_attempts(session, run.id)
        ],
        "judging": judging_summary(session, attempt),
        "models_count": len(snaps),
        "comparable": len(snaps) >= 2,
        "categories_present": [c for c in CATEGORIES if any(k.category == c for k in run.cases)],
        "leaderboard": rows,
    }


def case_key(case) -> tuple[str, str]:
    """Identity of a case across runs: same category and prompt text (works for ad-hoc and re-runs)."""
    return case.category, " ".join(case.prompt.split())


def per_case_scores(session: Session, run, attempt_id: int | None = None) -> dict[tuple[str, tuple[str, str]], dict]:
    """(model name, case key) -> {score, title} with repeats averaged. Unscored cases have score None."""
    attempt = (
        repo.latest_attempt(session, run.id)
        if attempt_id is None
        else next((a for a in repo.list_attempts(session, run.id) if a.id == attempt_id), None)
    )
    prim: dict[int, object] = {}
    if attempt:
        for s in repo.list_scores(session, run.id, attempt.id):
            prim[(s.result_id, s.kind)] = s
    cases = {c.id: c for c in run.cases}
    names = {s.id: s.name for s in repo.run_snapshots(session, run)}
    acc: dict = defaultdict(list)
    for r in repo.list_results(session, run.id):
        case = cases[r.run_case_id]
        s = prim.get((r.id, primary_kind(case.category)))
        acc[(names[r.model_snapshot_id], case_key(case))].append(
            (s.value if s else None, case.title or case.prompt[:60])
        )
    out = {}
    for k, vals in acc.items():
        nums = [v for v, _ in vals if v is not None]
        out[k] = {"score": sum(nums) / len(nums) if nums else None, "title": vals[0][1]}
    return out


def _delta(a, b):
    return None if a is None or b is None else b - a


def compare_runs(session: Session, run_a, run_b, weights: dict[str, float] | None = None) -> dict:
    """Deltas (B minus A) for models and cases present in both runs."""
    sa, sb = (build_summary(session, r, weights=weights) for r in (run_a, run_b))
    rows_a = {r["model"]: r for r in sa["leaderboard"]}
    rows_b = {r["model"]: r for r in sb["leaderboard"]}
    both = [m for m in rows_a if m in rows_b]

    def perf(row, key, stat="median"):
        return row["performance"][key][stat]

    models = []
    for m in both:
        a, b = rows_a[m], rows_b[m]
        cats = sorted(set(a["categories"]) & set(b["categories"]))
        models.append(
            {
                "model": m,
                "same_digest": a["digest"] == b["digest"],
                "composite": {
                    "a": a["composite"],
                    "b": b["composite"],
                    "delta": _delta(a["composite"], b["composite"]),
                },
                "categories": {
                    c: {
                        "a": a["categories"][c]["score"],
                        "b": b["categories"][c]["score"],
                        "delta": _delta(a["categories"][c]["score"], b["categories"][c]["score"]),
                    }
                    for c in cats
                },
                "performance": {
                    key: {"a": perf(a, key), "b": perf(b, key), "delta": _delta(perf(a, key), perf(b, key))}
                    for key in ("latency_ms", "ttft_ms", "tokens_per_s")
                },
            }
        )

    ca, cb = per_case_scores(session, run_a), per_case_scores(session, run_b)
    cases = []
    for model, key in sorted(set(ca) & set(cb), key=lambda k: (k[0], k[1])):
        cases.append(
            {
                "model": model,
                "category": key[0],
                "title": ca[(model, key)]["title"],
                "a": ca[(model, key)]["score"],
                "b": cb[(model, key)]["score"],
                "delta": _delta(ca[(model, key)]["score"], cb[(model, key)]["score"]),
            }
        )
    mode_a = (sa["attempt"] or {}).get("judge_mode", "none")
    mode_b = (sb["attempt"] or {}).get("judge_mode", "none")
    return {
        "judging": {"a": mode_a, "b": mode_b, "same": mode_a == mode_b},
        "a": {"id": run_a.id, "name": run_a.name, "status": run_a.status},
        "b": {"id": run_b.id, "name": run_b.name, "status": run_b.status},
        "models": models,
        "only_in_a": [m for m in rows_a if m not in rows_b],
        "only_in_b": [m for m in rows_b if m not in rows_a],
        "cases": cases,
    }
