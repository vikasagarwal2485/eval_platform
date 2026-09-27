"""Per-run circuit breakers for enterprise providers (design D8).

An authentication failure stops further requests to *that model*; a provider outage that survived its retries stops
further requests to *that provider*. Rate limits are transient and never trip a circuit. Local (Ollama) models are
never blocked here: an unreachable Ollama keeps failing the whole run as before.
"""

from __future__ import annotations

from app.providers.errors import ProviderAuthError, ProviderUnavailable
from app.providers.refs import is_cloud_ref, parse_ref


class Circuits:
    def __init__(self) -> None:
        self.models: dict[str, str] = {}  # model ref -> reason
        self.providers: dict[str, str] = {}  # provider name -> reason

    def blocked(self, ref: str) -> str | None:
        """Why a request to `ref` must not be sent, or None."""
        if not is_cloud_ref(ref):
            return None
        if ref in self.models:
            return f"Not sent: authentication failed earlier in this run ({self.models[ref]})"
        provider = parse_ref(ref).provider
        if provider in self.providers:
            return f"Not sent: provider '{provider}' was unavailable after retries earlier in this run ({self.providers[provider]})"
        return None

    def record(self, ref: str, exc: BaseException) -> str | None:
        """Note a failed request. Returns a warning to show when this opened a new circuit, else None."""
        if not is_cloud_ref(ref):
            return None
        if isinstance(exc, ProviderAuthError) and ref not in self.models:
            self.models[ref] = str(exc)
            return f"{ref}: authentication failed; its remaining requests in this run will not be sent"
        if isinstance(exc, ProviderUnavailable):
            provider = parse_ref(ref).provider
            if provider not in self.providers:
                self.providers[provider] = str(exc)
                return f"provider '{provider}' is unavailable; its remaining requests in this run will not be sent"
        return None
