"""add-otel-tracing 2.1: compute_cost never fabricates a figure - None, not 0, when it can't."""

from app.core.cost import compute_cost


def test_priced_model_computes_cost_from_the_price_list():
    # gpt-4o: 0.0025/1k input, 0.01/1k output (app/data/model_pricing.yaml)
    cost = compute_cost("gpt-4o", prompt_tokens=1000, completion_tokens=1000)
    assert cost == 0.0025 + 0.01


def test_dated_snapshot_matches_its_priced_family_by_longest_prefix():
    exact = compute_cost("gpt-4o", prompt_tokens=2000, completion_tokens=500)
    dated = compute_cost("gpt-4o-2024-08-06", prompt_tokens=2000, completion_tokens=500)
    assert dated == exact and dated is not None

    # "gpt-4o-mini" is the more specific (longer) prefix match, not "gpt-4o".
    mini_dated = compute_cost("gpt-4o-mini-2024-07-18", prompt_tokens=1000, completion_tokens=1000)
    mini_exact = compute_cost("gpt-4o-mini", prompt_tokens=1000, completion_tokens=1000)
    gpt4o_exact = compute_cost("gpt-4o", prompt_tokens=1000, completion_tokens=1000)
    assert mini_dated == mini_exact
    assert mini_dated != gpt4o_exact


def test_unpriced_model_returns_none_not_zero():
    assert compute_cost("qwen3:8b", prompt_tokens=500, completion_tokens=200) is None
    assert compute_cost("some-unknown-model-id", prompt_tokens=500, completion_tokens=200) is None


def test_missing_token_counts_return_none():
    assert compute_cost("gpt-4o", prompt_tokens=None, completion_tokens=200) is None
    assert compute_cost("gpt-4o", prompt_tokens=200, completion_tokens=None) is None
    assert compute_cost("gpt-4o", prompt_tokens=None, completion_tokens=None) is None


def test_missing_or_empty_model_returns_none():
    assert compute_cost(None, prompt_tokens=200, completion_tokens=200) is None
    assert compute_cost("", prompt_tokens=200, completion_tokens=200) is None
