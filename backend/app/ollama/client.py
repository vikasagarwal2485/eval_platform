"""Ollama REST client. All Ollama access goes through this module (design.md risks: API drift)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx


class OllamaError(Exception):
    """Ollama returned an error (HTTP status or error chunk)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OllamaUnreachable(OllamaError):
    """The Ollama server could not be contacted."""


class OllamaClient(Protocol):
    async def version(self) -> str: ...
    async def list_models(self) -> list[dict[str, Any]]: ...
    async def show(self, name: str) -> dict[str, Any]: ...
    async def ps(self) -> list[dict[str, Any]]: ...
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        format: Any = None,
        keep_alive: Any = None,
    ) -> AsyncIterator[dict[str, Any]]: ...
    async def unload(self, name: str) -> None: ...
    async def aclose(self) -> None: ...


class HttpOllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise OllamaUnreachable(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise OllamaError(_error_text(resp), status=resp.status_code)
        return resp.json()

    async def version(self) -> str:
        return (await self._request("GET", "/api/version")).get("version", "unknown")

    async def list_models(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/api/tags")).get("models", [])

    async def show(self, name: str) -> dict[str, Any]:
        return await self._request("POST", "/api/show", json={"model": name})

    async def ps(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/api/ps")).get("models", [])

    async def unload(self, name: str) -> None:
        # An empty chat request with keep_alive=0 unloads the model immediately.
        await self._request("POST", "/api/chat", json={"model": name, "messages": [], "keep_alive": 0})

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
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if options:
            body["options"] = options
        if think is not None:
            body["think"] = think
        if format is not None:
            body["format"] = format
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        try:
            async with self._client.stream("POST", "/api/chat", json=body) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise OllamaError(_error_text(resp), status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(str(chunk["error"]))
                    yield chunk
        except httpx.TransportError as exc:
            raise OllamaUnreachable(f"Connection to Ollama failed: {exc}") from exc


def _error_text(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", resp.text))
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


def is_thinking_capable(capabilities: list[str] | None) -> bool:
    return "thinking" in (capabilities or [])
