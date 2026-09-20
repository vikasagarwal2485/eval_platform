"""Deterministic checks on generated text (length, required/forbidden keywords)."""

from __future__ import annotations

import re

from app.core.scoring.base import ScoreResult

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def check_constraints(answer: str, constraints: dict | None) -> ScoreResult | None:
    """Return a pass/fail ScoreResult, or None when the case defines no constraints."""
    c = constraints or {}
    checks: list[dict] = []
    words = word_count(answer)
    if c.get("max_words"):
        checks.append(
            {"name": "max_words", "limit": c["max_words"], "actual": words, "passed": words <= c["max_words"]}
        )
    if c.get("min_words"):
        checks.append(
            {"name": "min_words", "limit": c["min_words"], "actual": words, "passed": words >= c["min_words"]}
        )
    lower = answer.casefold()
    for kw in c.get("required_keywords") or []:
        checks.append({"name": "required_keyword", "keyword": kw, "passed": kw.casefold() in lower})
    for kw in c.get("forbidden_keywords") or []:
        checks.append({"name": "forbidden_keyword", "keyword": kw, "passed": kw.casefold() not in lower})
    if not checks:
        return None
    ok = all(ch["passed"] for ch in checks)
    return ScoreResult("constraints", 1.0 if ok else 0.0, "pass" if ok else "fail", {"checks": checks, "words": words})
