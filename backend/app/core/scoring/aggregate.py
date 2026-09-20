"""Per-category and weighted composite scores (pure functions over score rows)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.schemas import CATEGORIES

DEFAULT_WEIGHTS = {c: 1.0 for c in CATEGORIES}


@dataclass
class ScoredItem:
    """One result's primary score. `case_id` groups repeats of the same case."""

    model_id: int
    case_id: int
    category: str
    value: float | None  # None = unscored (excluded from means)
    outcome: str = ""


def category_scores(items: list[ScoredItem]) -> dict[int, dict[str, dict]]:
    """model_id -> category -> {score, scored, total, errors, unparseable}.

    Repeats of a case are averaged first, then cases are averaged, so a case with more repeats does not
    dominate. Unscored cases are excluded from the mean but counted in `total`.
    """
    per_case: dict[tuple[int, str, int], list[ScoredItem]] = defaultdict(list)
    for it in items:
        per_case[(it.model_id, it.category, it.case_id)].append(it)

    grouped: dict[tuple[int, str], list[tuple[float | None, list[ScoredItem]]]] = defaultdict(list)
    for (model_id, cat, _), rows in per_case.items():
        vals = [r.value for r in rows if r.value is not None]
        grouped[(model_id, cat)].append((sum(vals) / len(vals) if vals else None, rows))

    out: dict[int, dict[str, dict]] = defaultdict(dict)
    for (model_id, cat), cases in grouped.items():
        scored = [v for v, _ in cases if v is not None]
        rows = [r for _, rs in cases for r in rs]
        out[model_id][cat] = {
            "score": sum(scored) / len(scored) if scored else None,
            "scored": len(scored),
            "total": len(cases),
            "errors": sum(1 for r in rows if r.outcome == "error"),
            "unparseable": sum(1 for r in rows if r.outcome == "unparseable"),
        }
    return dict(out)


def composite_score(cat_scores: dict[str, dict], weights: dict[str, float] | None = None) -> float | None:
    """Weighted mean over categories that have a score; weights are renormalized over those categories."""
    weights = weights or DEFAULT_WEIGHTS
    num = den = 0.0
    for cat, info in cat_scores.items():
        w = max(float(weights.get(cat, 0.0)), 0.0)
        if info.get("score") is None or w == 0:
            continue
        num += w * info["score"]
        den += w
    return num / den if den else None
