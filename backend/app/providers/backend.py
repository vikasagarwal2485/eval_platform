"""Backend abstraction (design D1): what a model backend can do, and the router that picks one per model.

Enterprise adapters translate provider streams into the *Ollama-shaped chunks* the runner, `StreamCollector`, the
judge and the scorers already consume, so none of them needs to know which provider produced a chunk.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app import repo
from app.models import Provider
from app.ollama.client import OllamaClient
from app.providers.errors import ProviderError
from app.providers.refs import parse_ref
from app.providers.secrets import KeyProvider, Redactor
from app.schemas import ModelInfo


@dataclass(frozen=True)
class BackendCaps:
    """What a backend supports; the runner skips steps a backend does not have."""

    warmup: bool  # a warm-up request makes sense (local model load)
    unload: bool  # can be unloaded to free memory
    footprint: bool  # memory footprint can be read
    seed: bool  # honours a random seed
    context_size: bool  # honours a context-window setting


LOCAL_CAPS = BackendCaps(warmup=True, unload=True, footprint=True, seed=True, context_size=True)
CLOUD_CAPS: dict[str, BackendCaps] = {
    "openai": BackendCaps(warmup=False, unload=False, footprint=False, seed=True, context_size=False),
    "anthropic": BackendCaps(warmup=False, unload=False, footprint=False, seed=False, context_size=False),
    "azure-openai": BackendCaps(warmup=False, unload=False, footprint=False, seed=True, context_size=False),
    # a registered `ollama` provider's models are exactly as local as an unregistered bare-name one
    # (`add-ollama-provider-kind`) - same capabilities, not the all-False fallback an unknown kind gets.
    "ollama": LOCAL_CAPS,
}


def caps_for_kind(provider_kind: str | None) -> BackendCaps:
    """Capabilities of a backend by provider kind (None = Ollama)."""
    if provider_kind is None:
        return LOCAL_CAPS
    return CLOUD_CAPS.get(provider_kind, BackendCaps(False, False, False, False, False))


def provider_availability(p: Provider, keys: KeyProvider) -> tuple[bool, str | None]:
    """(available, reason) for a registered provider - the single check reused everywhere a provider's models
    are listed, gated for selection, or preflighted before a run (`add-provider-availability-gating`).

    Two independent things can make a provider unusable, and only the second needs a cached result to catch:
    - its key env var isn't set right now (skipped for `ollama`/`custom`, neither of which has a key) - a cheap,
      always-live check;
    - its last "Test connection" call (`POST /providers/{id}/test`), if one was ever run, didn't succeed - a key
      that's present but wrong, or an Ollama server that's actually unreachable, looks identical to a working
      one under the first check alone. A provider that has never been tested is treated as available - this is
      a deliberate trade-off (see design.md): re-pinging every provider on every page load would add real
      latency and cost for something "Test connection" already exists to do explicitly; staleness is resolved by
      testing again, not by testing silently in the background."""
    if p.kind not in ("ollama", "custom") and not keys.available(p.key_env):
        return False, f"API key not set: environment variable {p.key_env} is empty"
    if p.last_test_status and p.last_test_status != "working":
        return False, f"Last connection test failed: {p.last_test_message or p.last_test_status}"
    return True, None


class ModelBackend(Protocol):
    kind: str

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        format: Any = None,
        keep_alive: Any = None,
        reasoning: bool = False,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def list_models(self) -> list[str]: ...
    async def ping(self, model: str | None = None, reasoning: bool = False) -> None: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class ProviderConfig:
    kind: str
    name: str
    key_env: str | None  # None for `ollama` - it has no key at all
    base_url: str | None
    api_version: str | None = None  # required by azure-openai; unused by other kinds


BackendFactory = Callable[[ProviderConfig, "ModelRouter"], ModelBackend]


@dataclass(frozen=True)
class Unavailable:
    ref: str
    reason: str


class ModelRouter:
    """Resolves a model reference to its backend. Exposes the surface the runner and judge already use
    (`chat_stream`, `unload`, `ps`, `version`, `list_models`, `show`), so it is a drop-in for the Ollama client."""

    def __init__(
        self,
        ollama: OllamaClient,
        session_factory: sessionmaker[Session],
        keys: KeyProvider | None = None,
        redactor: Redactor | None = None,
        factories: dict[str, BackendFactory] | None = None,
    ):
        self.ollama = ollama
        self.sf = session_factory
        self.keys = keys or KeyProvider()
        self.redactor = redactor or Redactor(self._registered_secrets)
        self.factories: dict[str, BackendFactory] = dict(factories or {})
        self._backends: dict[tuple, ModelBackend] = {}

    # ------------------------------------------------------------------ secrets
    def _registered_secrets(self) -> list[str]:
        try:
            with self.sf() as s:
                return [v for p in repo.list_providers(s) if (v := self.keys.get(p.key_env))]
        except Exception:  # noqa: BLE001 - redaction must never raise
            return []

    # ------------------------------------------------------------------ resolution
    def _resolve_cloud(self, provider_name: str, model_id: str) -> tuple[ModelBackend, bool, str | None]:
        """(backend, model is flagged reasoning, reasoning effort). Raises ProviderError if not registered."""
        with self.sf() as s:
            provider, model = repo.find_registered(s, provider_name, model_id)
            if provider is None:
                raise ProviderError(f"Provider '{provider_name}' is not registered", provider=provider_name)
            if model is None:
                raise ProviderError(
                    f"Model '{model_id}' is not registered under provider '{provider_name}'", provider=provider_name
                )
            cfg = ProviderConfig(
                provider.kind, provider.name, provider.key_env, provider.base_url, provider.api_version
            )
            reasoning, reasoning_effort = model.reasoning, model.reasoning_effort
        return self.backend_for(cfg), reasoning, reasoning_effort

    def backend_for(self, cfg: ProviderConfig) -> ModelBackend:
        """One backend instance per provider configuration; rebuilt if the configuration changes."""
        key = (cfg.kind, cfg.name, cfg.key_env, cfg.base_url, cfg.api_version)
        if key not in self._backends:
            factory = self.factories.get(cfg.kind)
            if factory is None:
                raise ProviderError(f"No adapter for provider kind '{cfg.kind}'", provider=cfg.name)
            self._backends = {k: v for k, v in self._backends.items() if k[1] != cfg.name}  # drop stale configs
            self._backends[key] = factory(cfg, self)
        return self._backends[key]

    # ------------------------------------------------------------------ the client surface
    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        format: Any = None,
        keep_alive: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        ref = parse_ref(model)
        if not ref.is_cloud:
            async for chunk in self.ollama.chat_stream(
                model=model, messages=messages, options=options, think=think, format=format, keep_alive=keep_alive
            ):
                yield chunk
            return
        backend, reasoning, reasoning_effort = self._resolve_cloud(ref.provider, ref.model)
        async for chunk in backend.chat_stream(
            model=ref.model,
            messages=messages,
            options=options,
            think=think,
            format=format,
            reasoning=reasoning,
            reasoning_effort=reasoning_effort,
        ):
            yield chunk

    async def unload(self, name: str) -> None:
        if not parse_ref(name).is_cloud:  # enterprise models have nothing to unload
            await self.ollama.unload(name)

    async def ps(self):
        return await self.ollama.ps()

    async def version(self) -> str:
        return await self.ollama.version()

    async def list_models(self):
        return await self.ollama.list_models()

    async def show(self, name: str):
        return await self.ollama.show(name)

    async def aclose(self) -> None:
        for backend in self._backends.values():
            await backend.aclose()
        await self.ollama.aclose()

    def model_info(self, ref: str) -> ModelInfo | None:
        """Description of a registered enterprise model (used to snapshot it for a run); None for Ollama names."""
        parsed = parse_ref(ref)
        if not parsed.is_cloud:
            return None
        with self.sf() as s:
            provider, model = repo.find_registered(s, parsed.provider, parsed.model)
            if provider is None or model is None:
                return None
            return ModelInfo(
                name=ref,
                digest="",  # providers publish no digest; the resolved model version is recorded per result
                source="cloud",
                provider=provider.name,
                provider_kind=provider.kind,
                display_name=model.display_name or model.model_id,
                reasoning=model.reasoning,
                capabilities=["completion"] + (["thinking"] if model.reasoning else []),
                thinking=model.reasoning,
            )

    # ------------------------------------------------------------------ preflight
    def preflight(self, refs: list[str]) -> list[Unavailable]:
        """Every enterprise reference that cannot be called right now, with the reason - including a registered
        `ollama`-kind provider (`add-ollama-provider-kind`) whose key... has none, but whose last connection test
        may still have failed (see `provider_availability`). Whether a specific model is still actually pulled
        is a separate, lighter-weight story (checked against the installed-model list), not this one."""
        problems: list[Unavailable] = []
        with self.sf() as s:
            for raw in dict.fromkeys(refs):
                try:
                    ref = parse_ref(raw)
                except ValueError as exc:
                    problems.append(Unavailable(raw, str(exc)))
                    continue
                if not ref.is_cloud:
                    continue
                provider, model = repo.find_registered(s, ref.provider, ref.model)
                if provider is None:
                    problems.append(Unavailable(raw, f"provider '{ref.provider}' is not registered"))
                    continue
                if model is None:
                    problems.append(Unavailable(raw, f"model '{ref.model}' is not registered under '{ref.provider}'"))
                    continue
                if not model.enabled:
                    problems.append(Unavailable(raw, "model is disabled"))
                    continue
                ok, reason = provider_availability(provider, self.keys)
                if not ok:
                    problems.append(Unavailable(raw, reason or "unavailable"))
        return problems
