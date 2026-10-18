"""Ollama adapter (`add-ollama-provider-kind`): lets a local Ollama server be registered and managed through the
same provider/model UI as an enterprise provider (`openai`, `anthropic`, `azure-openai`) - "Test connection",
"Fetch models", and per-model registration all work the same way, with no API key involved at all.

This wraps a fresh `HttpOllamaClient` pointed at this provider's own `base_url` (its Ollama server address,
defaulting to the application's configured one), translating `OllamaError`/`OllamaUnreachable` into the
`ProviderError` family the rest of `app/api/providers.py` already knows how to turn into a clean
test-connection/fetch-models response - there is no key to be missing or rejected, so no auth-specific
exception is ever raised here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings
from app.ollama.client import HttpOllamaClient, OllamaError, OllamaUnreachable
from app.providers.backend import ProviderConfig
from app.providers.errors import ProviderError, ProviderUnavailable
from app.providers.secrets import KeyProvider, Redactor

_CHAT_STREAM_KWARGS = ("model", "messages", "options", "think", "format", "keep_alive")


class OllamaBackend:
    kind = "ollama"

    def __init__(
        self,
        cfg: ProviderConfig,
        keys: KeyProvider,
        redactor: Redactor,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.cfg = cfg
        self.default_base_url = settings.ollama_base_url
        self._client = HttpOllamaClient(cfg.base_url or settings.ollama_base_url, transport=transport)

    async def ping(self, model: str | None = None, reasoning: bool = False) -> None:
        """Ignores `model`/`reasoning` (unlike azure-openai, there is no per-deployment concept to ping) - just
        confirms the server itself answers."""
        try:
            await self._client.version()
        except OllamaUnreachable as exc:
            raise ProviderUnavailable(str(exc), provider=self.cfg.name) from exc
        except OllamaError as exc:
            raise ProviderError(str(exc), status=exc.status, provider=self.cfg.name) from exc

    async def list_models(self) -> list[str]:
        try:
            entries = await self._client.list_models()
        except OllamaUnreachable as exc:
            raise ProviderUnavailable(str(exc), provider=self.cfg.name) from exc
        except OllamaError as exc:
            raise ProviderError(str(exc), status=exc.status, provider=self.cfg.name) from exc
        return [e["name"] for e in entries]

    def chat_stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        # Ollama has no `reasoning`/`reasoning_effort` request params (unlike the enterprise adapters) - drop
        # them rather than erroring, matching how ModelRouter already calls the shared Ollama client directly
        # for unregistered, bare-name local models.
        return self._client.chat_stream(**{k: v for k, v in kwargs.items() if k in _CHAT_STREAM_KWARGS})

    async def aclose(self) -> None:
        await self._client.aclose()
