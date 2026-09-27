"""Shared machinery for enterprise adapters: authenticated streaming with bounded retries, SSE parsing, error mapping.

Design D4/D8: the key is read at call time and sent only in an auth header; redirects are never followed (a key
must not travel to another host); every message that leaves this module is redacted; retries (rate limits, overload,
5xx, connection drops) happen *before the first byte* with exponential backoff, honouring `Retry-After`.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.providers.backend import ProviderConfig
from app.providers.errors import (
    ModelBackendError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.secrets import KeyProvider, Redactor

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MAX_RETRY_AFTER_S = 120.0


@dataclass
class Opened:
    """A successfully opened streaming response and how long it took to get there."""

    response: httpx.Response
    attempts: int
    retry_wait_ms: float  # time from the call start to the start of the successful attempt


class CloudBackend:
    kind = "cloud"
    default_base_url = ""

    def __init__(
        self,
        cfg: ProviderConfig,
        keys: KeyProvider,
        redactor: Redactor,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ):
        self.cfg, self.keys, self.redactor, self.settings = cfg, keys, redactor, settings
        self._sleep, self._clock, self._jitter = sleep, clock, jitter
        self._client = httpx.AsyncClient(
            base_url=(cfg.base_url or self.default_base_url).rstrip("/"),
            timeout=httpx.Timeout(300.0, connect=10.0),  # the run's own timeout governs the whole request
            follow_redirects=False,
            transport=transport,
        )

    # ------------------------------------------------------------------ hooks for subclasses
    def auth_headers(self, key: str) -> dict[str, str]:
        raise NotImplementedError

    def extract_error(self, body: Any) -> str:
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
            if body.get("message"):
                return str(body["message"])
        return ""

    def url(self, path: str) -> str:
        """Paths are given as `/v1/...`; a base URL that already ends in `/v1` is not doubled."""
        base = str(self._client.base_url).rstrip("/")
        return path[3:] if base.endswith("/v1") and path.startswith("/v1") else path

    # ------------------------------------------------------------------ plumbing
    async def aclose(self) -> None:
        await self._client.aclose()

    def _key(self) -> str:
        key = self.keys.get(self.cfg.key_env)
        if not key:
            raise ProviderAuthError(
                f"API key not set: environment variable {self.cfg.key_env} is empty", provider=self.cfg.name
            )
        return key

    def _clean(self, text: str) -> str:
        return self.redactor.redact(text)

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        cap = self.settings.provider_backoff_cap_s
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), MAX_RETRY_AFTER_S))
            except ValueError:
                pass  # an HTTP-date form: fall back to backoff
        base = self.settings.provider_backoff_s * (2**attempt)
        return min(cap, base * (0.5 + 0.5 * self._jitter()))

    async def _error_from(self, resp: httpx.Response) -> str:
        raw = (await resp.aread()).decode("utf-8", "replace")
        try:
            msg = self.extract_error(json.loads(raw))
        except json.JSONDecodeError:
            msg = ""
        return self._clean(msg or raw.strip()[:300] or f"HTTP {resp.status_code}")

    async def open_stream(self, method: str, path: str, *, json_body: dict | None = None) -> Opened:
        """Send a request and return the open streaming response (caller must close it), retrying before the first byte."""
        started = self._clock()
        max_attempts = 1 + max(0, self.settings.provider_max_retries)
        last_kind, last_msg, status = "unavailable", "", None
        for attempt in range(max_attempts):
            attempt_start = self._clock()
            key = self._key()  # read every attempt: a rotated key is picked up
            try:
                req = self._client.build_request(
                    method,
                    self.url(path),
                    json=json_body,
                    headers={**self.auth_headers(key), "content-type": "application/json"},
                )
                resp = await self._client.send(req, stream=True)
            except httpx.TransportError as exc:
                last_kind, last_msg, status = "unavailable", self._clean(f"cannot reach {self.cfg.name}: {exc}"), None
                retry_after = None
            else:
                if resp.status_code < 300:
                    return Opened(resp, attempt + 1, (attempt_start - started) * 1000.0)
                status = resp.status_code
                if 300 <= status < 400:  # never followed: the key must not travel to another host
                    await resp.aclose()
                    raise ProviderError(
                        self._clean(f"unexpected redirect (HTTP {status}); check the provider's base URL"),
                        status=status,
                        provider=self.cfg.name,
                    )
                last_msg = await self._error_from(resp)
                retry_after = resp.headers.get("retry-after")
                await resp.aclose()
                if status in (401, 403):
                    raise ProviderAuthError(last_msg or "authentication failed", status=status, provider=self.cfg.name)
                if status not in RETRYABLE_STATUS:
                    raise ProviderError(last_msg, status=status, provider=self.cfg.name)
                last_kind = "rate_limited" if status == 429 else "unavailable"
            if attempt + 1 < max_attempts:
                await self._sleep(self._retry_delay(attempt, retry_after))
        cls = ProviderRateLimited if last_kind == "rate_limited" else ProviderUnavailable
        raise cls(f"{last_msg} (gave up after {max_attempts} attempts)", status=status, provider=self.cfg.name)

    async def request_json(self, method: str, path: str) -> Any:
        """Simple authenticated JSON request with the same retry and error rules (model lists, connection test)."""
        opened = await self.open_stream(method, path)
        try:
            return json.loads((await opened.response.aread()).decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable("provider returned invalid JSON", provider=self.cfg.name) from exc
        finally:
            await opened.response.aclose()

    async def ping(self) -> None:
        await self.list_models()

    async def list_models(self) -> list[str]:
        raise NotImplementedError

    def chat_stream(self, **kwargs) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError


async def iter_sse(resp: httpx.Response) -> AsyncIterator[tuple[str | None, str]]:
    """Yield (event, data) for each server-sent event. Multi-line data is joined with newlines."""
    event: str | None = None
    data: list[str] = []
    async for line in resp.aiter_lines():
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith(":"):
            continue  # comment / keep-alive
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield event, "\n".join(data)


def final_chunk(*, done_reason: str, prompt_tokens: int | None, output_tokens: int | None, provider: dict) -> dict:
    """The Ollama-shaped final chunk (design D1). Durations are deliberately absent: they are not reported."""
    chunk: dict[str, Any] = {
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": done_reason,
        "_provider": provider,
    }
    if prompt_tokens is not None:
        chunk["prompt_eval_count"] = prompt_tokens
    if output_tokens is not None:
        chunk["eval_count"] = output_tokens
    return chunk


def text_chunk(content: str = "", thinking: str = "") -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if thinking:
        msg["thinking"] = thinking
    return {"message": msg, "done": False}


__all__ = ["CloudBackend", "Opened", "iter_sse", "final_chunk", "text_chunk", "ModelBackendError"]
