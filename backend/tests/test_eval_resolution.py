from dataclasses import dataclass

from app.core.eval_resolution import resolve_evaluators


@dataclass
class _Unavailable:
    ref: str
    reason: str


class _StubRouter:
    """Only cloud refs can be made unavailable, mirroring the real ModelRouter.preflight contract."""

    def __init__(self, bad: dict[str, str] | None = None):
        self.bad = bad or {}

    def preflight(self, refs):
        return [_Unavailable(r, self.bad[r]) for r in refs if r in self.bad]


def test_all_evaluators_available():
    r = resolve_evaluators(_StubRouter(), ["b", "c"], ["a"], installed_local={"b", "c"})
    assert r.available == ["b", "c"]
    assert r.skip_reason is None


def test_one_evaluator_unavailable_others_still_used():
    router = _StubRouter({"@openai-main/gpt-4o": "API key not set"})
    r = resolve_evaluators(router, ["b", "@openai-main/gpt-4o"], ["a"], installed_local={"b"})
    assert r.available == ["b"]
    assert r.unavailable == {"@openai-main/gpt-4o": "API key not set"}
    assert r.skip_reason is None


def test_all_evaluators_unavailable():
    router = _StubRouter({"b": "not installed in Ollama"})
    r = resolve_evaluators(router, ["b"], ["a"], installed_local=set())
    assert r.available == []
    assert r.skip_reason == "no_eligible_evaluator"


def test_identity_skip_takes_priority_over_availability():
    r = resolve_evaluators(_StubRouter(), ["a"], ["a"], installed_local={"a"})
    assert r.skip_reason == "no_eligible_evaluator"
    assert r.available == []


def test_models_unknown_skips_before_any_availability_check():
    r = resolve_evaluators(_StubRouter(), ["b"], [], models_unknown=True)
    assert r.skip_reason == "agent_model_unknown"


def test_local_evaluator_not_installed_is_unavailable():
    r = resolve_evaluators(_StubRouter(), ["b"], ["a"], installed_local={"c"})
    assert r.available == []
    assert r.unavailable == {"b": "not installed in Ollama"}
