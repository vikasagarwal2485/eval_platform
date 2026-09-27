"""Small helpers describing where a model runs (local Ollama or an enterprise provider)."""

from __future__ import annotations

from app.providers.refs import is_cloud_ref, parse_ref


def provider_of(name: str) -> str | None:
    """Registered provider name for an enterprise reference; None for Ollama models."""
    return parse_ref(name).provider if is_cloud_ref(name) else None


def versions_by_model(results) -> dict[int, list[str]]:
    """snapshot id -> distinct model versions the provider reported across a run's results."""
    out: dict[int, set[str]] = {}
    for r in results:
        v = (r.metrics or {}).get("model_version")
        if v:
            out.setdefault(r.model_snapshot_id, set()).add(v)
    return {k: sorted(v) for k, v in out.items()}
