"""Reasoning scoring: extract the final answer, then compare (text or numeric with tolerance)."""

from __future__ import annotations

import re

from app.core.scoring.base import ScoreResult
from app.core.text import normalize, parse_number

_FINAL = re.compile(r"final\s+answer\s*(?:is)?\s*[:\-=]?\s*", re.I)
_ANSWER_IS = re.compile(r"(?:the\s+)?answer\s+is\s*[:\-]?\s*", re.I)
_BOXED = re.compile(r"\\boxed\{([^{}]*)\}")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:\s*/\s*\d+)?%?")


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[\s*_`<>\[\]()$]+|[\s*_`<>\[\]()]+$", "", text)
    return text.strip(" .")


def _after_last(pattern: re.Pattern, text: str) -> str | None:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    rest = text[matches[-1].end() :]
    line = next((ln for ln in rest.splitlines() if ln.strip()), "")
    return _clean(line) or None


def extract_final_answer(answer: str) -> tuple[str | None, str]:
    """Return (final_answer|None, method). Methods: marker | boxed | answer_is | fallback | none."""
    if not answer.strip():
        return None, "none"
    got = _after_last(_FINAL, answer)
    if got:
        return got, "marker"
    boxed = _BOXED.findall(answer)
    if boxed:
        return _clean(boxed[-1]), "boxed"
    got = _after_last(_ANSWER_IS, answer)
    if got:
        return got, "answer_is"
    last_line = next((ln for ln in reversed(answer.splitlines()) if ln.strip()), "")
    return (_clean(last_line) or None), "fallback"


def _last_number(text: str) -> float | None:
    nums = _NUMBER.findall(text)
    return parse_number(nums[-1]) if nums else None


def score_reasoning(answer: str, expected: str | None, comparison: str = "text", tolerance: float = 0.0) -> ScoreResult:
    final, method = extract_final_answer(answer)
    detail: dict = {"final_answer": final, "method": method, "expected": expected, "comparison": comparison}

    if comparison == "numeric":
        got: float | None = None
        if final and method != "fallback":
            got = parse_number(final)
        elif method == "fallback":
            # No explicit marker: use the last number on the last line, else anywhere in the answer.
            got = _last_number(final or "")
            if got is None:
                got = _last_number(answer)
            if got is not None:
                detail["method"] = "last_number"
        detail["parsed"] = got
        if got is None:
            return ScoreResult(
                "auto",
                0.0 if expected is not None else None,
                "unparseable" if expected is not None else "unscored",
                detail,
            )
        if expected is None:
            return ScoreResult("auto", None, "unscored", detail)
        want = parse_number(expected)
        ok = want is not None and abs(got - want) <= tolerance + 1e-9
        return ScoreResult("auto", 1.0 if ok else 0.0, "correct" if ok else "wrong", detail)

    # text comparison
    if final is None:
        return ScoreResult(
            "auto", 0.0 if expected is not None else None, "unparseable" if expected is not None else "unscored", detail
        )
    if expected is None:
        return ScoreResult("auto", None, "unscored", detail)
    got_n, want_n = normalize(final), normalize(expected)
    ok = got_n == want_n
    if not ok and method == "fallback":
        # Without an explicit marker accept an answer that *starts with* the expected text ("Yes, because ...").
        ok = got_n.startswith(want_n + " ")
    return ScoreResult("auto", 1.0 if ok else 0.0, "correct" if ok else "wrong", detail)
