"""Tempo trace-query client (add-otel-tracing decision 4).

Fetch-trace-by-id only - the only query this platform needs; no TraceQL search UI. Mirrors
`app/ollama/client.py`'s shape: a thin `httpx.AsyncClient` wrapper, an injectable `transport` for
tests, and the same "unreachable vs. an actual error response" distinction.
"""

from __future__ import annotations

from typing import Any

import httpx


class TempoError(Exception):
    """Tempo was reached but returned something other than a trace or a clean 404."""


class TempoUnreachable(TempoError):
    """Tempo could not be contacted at all."""


class TempoClient:
    def __init__(self, base_url: str, timeout_s: float = 5.0, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=httpx.Timeout(timeout_s, connect=2.0), transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """The raw trace JSON, or `None` if Tempo has no trace with that id.

        Raises `TempoUnreachable` if Tempo could not be contacted, `TempoError` for any other
        response that isn't a clean 200 or 404 (a malformed body, an unexpected status)."""
        try:
            resp = await self._client.get(f"/api/traces/{trace_id}")
        except httpx.TransportError as exc:
            raise TempoUnreachable(f"Cannot reach Tempo at {self.base_url}: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise TempoError(f"Tempo returned HTTP {resp.status_code} for trace {trace_id}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TempoError(f"Tempo returned a non-JSON response for trace {trace_id}") from exc
