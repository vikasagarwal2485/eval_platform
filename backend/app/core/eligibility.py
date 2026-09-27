"""The evaluator invariant: a model never evaluates a turn it helped produce (design D5).

Pure and Ollama-free, like `plan_judgements` for benchmark runs, so the invariant is unit-testable without a
running Ollama or any provider. `same_model`/`same_family` are also used directly by agent settings validation
(an evaluator equal to the declared model is rejected at save time).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.providers.refs import parse_ref

DigestLookup = Callable[[str], str | None]


def _base_family(model_id: str) -> str:
    """The part of a model id before its first ':' - `qwen3` for `qwen3:8b` and for `qwen3:latest`."""
    return model_id.split(":", 1)[0]


def same_model(a: str, b: str, digest_of: DigestLookup | None = None) -> bool:
    """True if `a` and `b` refer to the same model.

    Two enterprise references match only on (provider, model id) - providers report no digest. Two Ollama names
    match on the normalized reference, or, when `digest_of` resolves both to the same non-empty digest, on that
    (so `qwen3:8b` and `qwen3:latest` count as the same model when they resolve to one download).
    """
    try:
        ra, rb = parse_ref(a), parse_ref(b)
    except ValueError:
        return a == b
    if ra == rb:
        return True
    if ra.is_cloud or rb.is_cloud:
        return False  # cloud references never match by digest; providers report none
    if digest_of is not None:
        da, db = digest_of(a), digest_of(b)
        if da and db and da == db:
            return True
    return False


def same_family(a: str, b: str) -> bool:
    """True if `a` and `b` are different models of the same family/provider (e.g. `qwen3:8b` vs `qwen3:32b`)."""
    try:
        ra, rb = parse_ref(a), parse_ref(b)
    except ValueError:
        return False
    if ra.provider != rb.provider:
        return False
    return ra.model != rb.model and _base_family(ra.model) == _base_family(rb.model)


@dataclass(frozen=True)
class EvaluatorPlan:
    """Which of an agent's configured evaluators may score one turn, by identity alone (no availability check)."""

    eligible: list[str] = field(default_factory=list)
    same_family: list[str] = field(default_factory=list)  # eligible evaluators flagged as likely self-preference
    skip_reason: str | None = None  # set (and eligible empty) when the turn cannot be evaluated at all


def plan_turn_evaluators(
    evaluators: list[str],
    turn_models: list[str],
    *,
    models_unknown: bool = False,
    digest_of: DigestLookup | None = None,
) -> EvaluatorPlan:
    """Who may evaluate a turn, given the models that actually produced it.

    `models_unknown` or an empty `turn_models` means the agent did not report which model(s) it used: the turn is
    never evaluated by default rather than assumed safe to judge with anything (design D5/spec `trace-ingestion`).
    """
    if models_unknown or not turn_models:
        return EvaluatorPlan(skip_reason="agent_model_unknown")
    eligible: list[str] = []
    flagged: list[str] = []
    for e in evaluators:
        if any(same_model(e, m, digest_of) for m in turn_models):
            continue  # this evaluator produced (part of) the turn: never eligible for it
        eligible.append(e)
        if any(same_family(e, m) for m in turn_models):
            flagged.append(e)
    if not eligible:
        return EvaluatorPlan(skip_reason="no_eligible_evaluator")
    return EvaluatorPlan(eligible=eligible, same_family=flagged)
