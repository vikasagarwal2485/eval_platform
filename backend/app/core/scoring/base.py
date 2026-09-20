from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    """kind: auto | constraints | judge | judge_reasoning.
    value is 0..1 or None when unscored. outcome: correct | wrong | unparseable | error |
    unscored | pass | fail | judged."""

    kind: str
    value: float | None
    outcome: str
    detail: dict = field(default_factory=dict)
