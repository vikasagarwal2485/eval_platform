"""Discover installed Ollama models and normalize them for the API."""

from __future__ import annotations

from app.ollama.client import OllamaClient, OllamaError, is_thinking_capable
from app.schemas import ModelInfo


class ModelDiscovery:
    """Lists models; caches per-digest capabilities fetched via /api/show."""

    def __init__(self, client: OllamaClient):
        self.client = client
        self._caps: dict[str, list[str]] = {}

    def clear_cache(self) -> None:
        self._caps.clear()

    async def _capabilities(self, entry: dict) -> list[str]:
        if "capabilities" in entry:  # newer Ollama includes them in /api/tags
            return list(entry["capabilities"] or [])
        digest = entry.get("digest", "")
        if digest in self._caps:
            return self._caps[digest]
        try:
            caps = list((await self.client.show(entry["name"])).get("capabilities") or [])
        except OllamaError:
            caps = []
        self._caps[digest] = caps
        return caps

    async def list_models(self, refresh: bool = False) -> list[ModelInfo]:
        if refresh:
            self.clear_cache()
        out: list[ModelInfo] = []
        for e in await self.client.list_models():
            d = e.get("details") or {}
            caps = await self._capabilities(e)
            out.append(
                ModelInfo(
                    name=e["name"],
                    digest=e.get("digest", ""),
                    size_bytes=e.get("size"),
                    parameter_size=d.get("parameter_size"),
                    quantization=d.get("quantization_level"),
                    family=d.get("family"),
                    capabilities=caps,
                    thinking=is_thinking_capable(caps),
                )
            )
        return sorted(out, key=lambda m: m.name)
