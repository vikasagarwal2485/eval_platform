"""Shared helpers for provider adapter tests."""

from __future__ import annotations

from app.config import Settings
from app.providers.backend import ProviderConfig
from app.providers.secrets import KeyProvider, Redactor

KEY = "test-key-123"


class Sleeps:
    """Records requested sleeps instead of waiting."""

    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float):
        self.calls.append(seconds)


def settings(retries=2, backoff=0.5, cap=30.0):
    return Settings(provider_max_retries=retries, provider_backoff_s=backoff, provider_backoff_cap_s=cap)


def make(
    cls,
    kind: str,
    url: str | None,
    *,
    key=KEY,
    retries=2,
    backoff=0.5,
    cap=30.0,
    transport=None,
    sleeps=None,
    jitter=lambda: 1.0,
    name="prov",
    key_env="PROV_KEY",
):
    env = {key_env: key} if key is not None else {}
    keys = KeyProvider(env)
    backend = cls(
        ProviderConfig(kind, name, key_env, url),
        keys,
        Redactor(lambda: [v for v in env.values()]),
        settings(retries, backoff, cap),
        transport=transport,
        sleep=sleeps or Sleeps(),
        jitter=jitter,
    )
    backend.env = env
    return backend


async def collect(agen):
    return [c async for c in agen]


def text_of(chunks) -> str:
    return "".join(c["message"].get("content", "") for c in chunks)


def thinking_of(chunks) -> str:
    return "".join(c["message"].get("thinking", "") for c in chunks)
