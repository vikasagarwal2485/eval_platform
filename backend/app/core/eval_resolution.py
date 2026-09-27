"""Which evaluators may actually be called for a turn right now (design D5, tasks 1.3 + 4.1).

Two independent questions, kept separate on purpose: identity (`plan_turn_evaluators`, pure, no I/O - a model
never evaluates a turn it helped produce) and availability (`router.preflight` plus, for local Ollama names, the
installed-model list - an evaluator can be eligible by identity and still be temporarily uncallable). An
unavailable evaluator is skipped with its own reason; it never falls back to an ineligible model, and it never
fails the other evaluators in the same panel (spec `live-evaluation`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.eligibility import DigestLookup, plan_turn_evaluators
from app.providers.backend import ModelRouter
from app.providers.refs import is_cloud_ref


@dataclass(frozen=True)
class ResolvedEvaluators:
    available: list[str] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)  # evaluator ref -> reason it was skipped
    same_family: list[str] = field(default_factory=list)
    skip_reason: str | None = None  # set (and `available` empty) when the turn cannot be evaluated at all


def resolve_evaluators(
    router: ModelRouter,
    evaluators: list[str],
    turn_models: list[str],
    *,
    models_unknown: bool = False,
    digest_of: DigestLookup | None = None,
    installed_local: Iterable[str] | None = None,
) -> ResolvedEvaluators:
    plan = plan_turn_evaluators(evaluators, turn_models, models_unknown=models_unknown, digest_of=digest_of)
    if plan.skip_reason:
        return ResolvedEvaluators(skip_reason=plan.skip_reason)

    problems: dict[str, str] = {u.ref: u.reason for u in router.preflight(plan.eligible)}
    if installed_local is not None:
        installed = set(installed_local)
        for e in plan.eligible:
            if not is_cloud_ref(e) and e not in installed and e not in problems:
                problems[e] = "not installed in Ollama"

    available = [e for e in plan.eligible if e not in problems]
    skip_reason = None if available else "no_eligible_evaluator"
    return ResolvedEvaluators(available, problems, plan.same_family, skip_reason)
