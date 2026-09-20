"""In-memory fake Ollama client for tests (no live server needed)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from app.ollama.client import OllamaError, OllamaUnreachable

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    text = (FIXTURES / name).read_text()
    if name.endswith(".ndjson"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def make_tag(name: str, *, thinking: bool = False, size: int = 1_000_000_000) -> dict:
    return {
        "name": name,
        "model": name,
        "size": size,
        "digest": f"digest-{name}",
        "details": {"family": name.split(":")[0], "parameter_size": "8B", "quantization_level": "Q4_K_M"},
        "capabilities": ["completion"] + (["thinking"] if thinking else []),
    }


def make_stream(
    answer: str,
    *,
    thinking: str | None = None,
    eval_count: int | None = None,
    eval_duration_ns: int = 1_000_000_000,
    load_duration_ns: int = 5_000_000,
    delay_s: float = 0.0,
) -> list[dict]:
    chunks: list[dict] = []
    if thinking:
        for w in thinking.split(" "):
            chunks.append({"message": {"role": "assistant", "content": "", "thinking": w + " "}, "done": False})
    words = answer.split(" ")
    for i, w in enumerate(words):
        piece = w + (" " if i < len(words) - 1 else "")
        chunks.append({"message": {"role": "assistant", "content": piece}, "done": False})
    n = eval_count if eval_count is not None else len(words) + len((thinking or "").split())
    chunks.append(
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "total_duration": load_duration_ns + eval_duration_ns + 100_000_000,
            "load_duration": load_duration_ns,
            "prompt_eval_count": 20,
            "prompt_eval_duration": 100_000_000,
            "eval_count": n,
            "eval_duration": eval_duration_ns,
        }
    )
    return chunks


class FakeOllama:
    """Scriptable fake. `responder(model, messages, options)` returns a list of chunks or raises."""

    def __init__(
        self,
        models: list[dict] | None = None,
        responder: Callable[[str, list[dict], dict], list[dict]] | None = None,
        *,
        version: str = "0.34.2",
        down: bool = False,
        chunk_delay_s: float = 0.0,
        strict_models: bool = False,
    ):
        self._models = models if models is not None else [make_tag("qwen3:8b", thinking=True)]
        self.responder = responder or (lambda m, msgs, o: make_stream("ok"))
        self._version = version
        self.down = down
        self.chunk_delay_s = chunk_delay_s
        self.judge_chunk_delay_s = 0.0  # extra delay per chunk for judge requests (those sending a JSON schema)
        self.strict_models = strict_models  # unknown models raise a 404-style error, like Ollama
        self.calls: list[tuple] = []  # ordered log of ("chat"|"unload"|..., model)
        self.loaded: set[str] = set()
        self.ps_data: list[dict] = []

    def _check(self):
        if self.down:
            raise OllamaUnreachable("Cannot reach Ollama at fake")

    async def version(self) -> str:
        self._check()
        return self._version

    async def list_models(self) -> list[dict]:
        self._check()
        return list(self._models)

    async def show(self, name: str) -> dict:
        self._check()
        for m in self._models:
            if m["name"] == name:
                return {"capabilities": m.get("capabilities", []), "details": m["details"]}
        raise OllamaError("model not found", status=404)

    async def ps(self) -> list[dict]:
        self._check()
        if self.ps_data:
            return self.ps_data
        return [{"name": n, "size": 2_000_000_000, "size_vram": 2_000_000_000} for n in sorted(self.loaded)]

    async def unload(self, name: str) -> None:
        self._check()
        self.calls.append(("unload", name))
        self.loaded.discard(name)

    async def chat_stream(
        self, *, model, messages, options=None, think=None, format=None, keep_alive=None
    ) -> AsyncIterator[dict]:
        self._check()
        if self.strict_models and model not in {m["name"] for m in self._models}:
            raise OllamaError(f"model '{model}' not found", status=404)
        self.calls.append(("chat", model, dict(options or {}), think, format))
        self.loaded.add(model)
        chunks = self.responder(model, messages, options or {})
        delay = self.judge_chunk_delay_s if format is not None else self.chunk_delay_s
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield c

    async def aclose(self) -> None:
        pass
