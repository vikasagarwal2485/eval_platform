"""Adapter factories for the router (kept apart so tests can inject an HTTP transport)."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.providers.anthropic import AnthropicBackend
from app.providers.backend import BackendFactory, ProviderConfig
from app.providers.openai import OpenAIBackend


def make_factories(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, BackendFactory]:
    def build(cls):
        def factory(cfg: ProviderConfig, router) -> object:
            return cls(cfg, router.keys, router.redactor, settings, transport=transport)

        return factory

    return {"openai": build(OpenAIBackend), "anthropic": build(AnthropicBackend)}
