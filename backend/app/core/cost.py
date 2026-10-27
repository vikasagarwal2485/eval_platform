"""Cost calculation from the maintained price list (add-otel-tracing design.md decision 7).

Pure and side-effect free: `compute_cost()` never fabricates a figure. It returns `None` - never
0.0 - whenever the model has no price-list entry or either token count is missing, the same
"absent means unknown, not zero" convention `cached_tokens` already follows (`core/metrics.py`).
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

_PRICE_FILE = Path(__file__).resolve().parents[1] / "data" / "model_pricing.yaml"


@functools.lru_cache(maxsize=1)
def _load_prices() -> dict[str, dict[str, float]]:
    """Parsed once per process. Tests that swap `_PRICE_FILE` must call `_load_prices.cache_clear()`."""
    if not _PRICE_FILE.exists():
        return {}
    data = yaml.safe_load(_PRICE_FILE.read_text()) or {}
    return data.get("models") or {}


def compute_cost(model: str | None, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """USD cost for one request, or None when it cannot be computed.

    `model` must be the resolved model identifier a provider actually reports (e.g. the
    `model_version` on a cloud result, or an Ollama model's bare name) - never this platform's
    `@provider/model` reference and never an Azure deployment's own alias, since either can be
    arbitrary and unrelated to what's priced here.
    """
    if not model or prompt_tokens is None or completion_tokens is None:
        return None
    prices = _load_prices()
    entry = prices.get(model)
    if entry is None:
        # A provider often reports a dated snapshot (e.g. "gpt-4o-2024-08-06") for a priced family
        # ("gpt-4o"). Match the longest price-list key the model id starts with, so the most
        # specific family entry wins (e.g. "gpt-4o-mini" over "gpt-4o" for "gpt-4o-mini-2024-07-18").
        candidates = [key for key in prices if model.startswith(key)]
        if candidates:
            entry = prices[max(candidates, key=len)]
    if entry is None:
        return None
    input_per_1k, output_per_1k = entry.get("input_per_1k"), entry.get("output_per_1k")
    if input_per_1k is None or output_per_1k is None:
        return None
    return (prompt_tokens / 1000.0) * input_per_1k + (completion_tokens / 1000.0) * output_per_1k
