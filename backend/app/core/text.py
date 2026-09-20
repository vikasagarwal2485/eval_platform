"""Small text helpers shared by validation and scoring."""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s\-./%]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold, strip accents' decoration, punctuation (keeps - . / %) and collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip(" .")


def parse_number(text: str) -> float | None:
    """Parse the first number in text (supports 1,234.5, -3, 50%, 1/2)."""
    t = text.strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?\s*/\s*-?\d+(?:\.\d+)?", t)
    if m:
        a, b = (float(x) for x in re.split(r"\s*/\s*", m.group(0)))
        return a / b if b else None
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", t)
    return float(m.group(0)) if m else None
