"""Classification scoring: normalize, find an allowed label, compare with the expected label."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from app.core.scoring.base import ScoreResult
from app.core.text import normalize

UNPARSEABLE = "unparseable"
_MARKER = re.compile(r"(?:final answer|answer|label|classification|category|prediction)\s*[:=\-]\s*", re.I)


def _match_form(text: str) -> str:
    """Normalized form used only for matching: underscores/hyphens behave like spaces."""
    return " ".join(re.sub(r"[_\-]", " ", normalize(text)).split())


def find_labels(answer: str, labels: list[str]) -> list[tuple[int, str]]:
    """Return [(position, label)] for allowed labels found in the answer, in text order.

    Longer labels are matched first and their span masked, so `spam` is not found inside `not spam`.
    """
    text = _match_form(answer)
    found: list[tuple[int, str]] = []
    for label in sorted(labels, key=lambda lab: len(_match_form(lab)), reverse=True):
        needle = _match_form(label)
        if not needle:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
        for m in pattern.finditer(text):
            found.append((m.start(), label))
            text = text[: m.start()] + "#" * (m.end() - m.start()) + text[m.end() :]
    return sorted(found)


def predict_label(answer: str, labels: list[str]) -> tuple[str | None, dict]:
    """Pick the predicted label. Exact answer wins; then text after an explicit marker; then the
    first label mentioned. Returns (label|None, detail)."""
    detail: dict = {"ambiguous": False, "candidates": []}
    norm_answer = _match_form(answer)
    for label in labels:
        if norm_answer == _match_form(label):
            detail["method"] = "exact"
            return label, detail

    search = answer
    markers = list(_MARKER.finditer(answer))
    if markers:
        after = answer[markers[-1].end() :]
        if find_labels(after, labels):
            search, detail["method"] = after, "marker"
    found = find_labels(search, labels)
    detail.setdefault("method", "first_mention")
    if not found:
        detail["method"] = "none"
        return None, detail
    distinct = list(dict.fromkeys(lab for _, lab in found))
    detail["candidates"] = distinct
    detail["ambiguous"] = len(distinct) > 1
    return distinct[0], detail


def score_classification(answer: str, labels: list[str], expected: str | None) -> ScoreResult:
    predicted, detail = predict_label(answer, labels)
    detail["predicted"] = predicted
    detail["expected"] = expected
    if predicted is None:
        # Unparseable is a failure mode of its own but still counts as incorrect when ground truth exists.
        return ScoreResult(
            "auto", 0.0 if expected is not None else None, UNPARSEABLE if expected is not None else "unscored", detail
        )
    if expected is None:
        return ScoreResult("auto", None, "unscored", detail)
    ok = _match_form(predicted) == _match_form(expected)
    return ScoreResult("auto", 1.0 if ok else 0.0, "correct" if ok else "wrong", detail)


def classification_metrics(pairs: list[tuple[str, str | None]]) -> dict:
    """Aggregate metrics from (expected, predicted|None) pairs.

    Accuracy counts unparseable predictions as wrong. Precision/recall/F1 are per label; the
    confusion matrix has an extra `unparseable` column. Returns matrix=None below two labels.
    """
    if not pairs:
        return {"n": 0, "accuracy": None, "per_label": {}, "confusion": None, "unparseable": 0}
    labels = sorted({e for e, _ in pairs} | {p for _, p in pairs if p})
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    support: Counter = Counter()
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    correct = unparseable = 0
    for exp, pred in pairs:
        support[exp] += 1
        matrix[exp][pred or UNPARSEABLE] += 1
        if pred is None:
            unparseable += 1
            fn[exp] += 1
        elif pred == exp:
            correct += 1
            tp[exp] += 1
        else:
            fp[pred] += 1
            fn[exp] += 1
    per_label = {}
    for lab in labels:
        p = tp[lab] / (tp[lab] + fp[lab]) if (tp[lab] + fp[lab]) else None
        r = tp[lab] / (tp[lab] + fn[lab]) if (tp[lab] + fn[lab]) else None
        f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
        per_label[lab] = {"precision": p, "recall": r, "f1": f1, "support": support[lab]}
    confusion = None
    if len(labels) >= 2:
        cols = labels + ([UNPARSEABLE] if unparseable else [])
        confusion = {"labels": cols, "rows": {lab: {c: matrix[lab].get(c, 0) for c in cols} for lab in labels}}
    return {
        "n": len(pairs),
        "accuracy": correct / len(pairs),
        "per_label": per_label,
        "confusion": confusion,
        "unparseable": unparseable,
    }
