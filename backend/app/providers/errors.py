"""Errors raised by model backends (Ollama and enterprise providers).

`ModelBackendError` is the base for anything that fails one request and should be recorded against it.
`OllamaUnreachable` (defined next to the Ollama client) stays a special case: it fails the whole run.
"""

from __future__ import annotations


class ModelBackendError(Exception):
    """A request to a model backend failed."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ProviderError(ModelBackendError):
    """An enterprise provider (OpenAI, Anthropic, ...) failed a request."""

    def __init__(self, message: str, status: int | None = None, provider: str | None = None):
        super().__init__(message, status)
        self.provider = provider


class ProviderAuthError(ProviderError):
    """The provider rejected the API key (401/403) or no key is available."""


class ProviderRateLimited(ProviderError):
    """Rate limited and retries were exhausted."""


class ProviderUnavailable(ProviderError):
    """Provider overloaded, erroring or unreachable and retries were exhausted."""
