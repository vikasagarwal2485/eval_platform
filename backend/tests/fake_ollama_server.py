"""A fake Ollama that speaks the real HTTP/NDJSON protocol, for end-to-end tests.

It replays the *recorded* thinking stream (tests/fixtures/chat_stream_think.ndjson) for the reasoning
prompt, and scripts everything else. Runs in a background thread on a free port.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
from collections.abc import Iterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from tests.fakes import load_fixture, make_stream, make_tag

MODELS = [make_tag("qwen3:8b", thinking=True), make_tag("gemma:test"), make_tag("judge:test")]


class FakeOllamaServer:
    def __init__(self) -> None:
        self.requests: list[dict] = []  # every /api/chat body, in order
        self.loaded: set[str] = set()
        # model -> answer to classification prompts
        self.judge_scores = {}  # judge model -> 1-5 score it gives (default 4)
        self.classification = {"qwen3:8b": "positive", "gemma:test": "Negative.", "judge:test": "positive"}
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    # ---------------------------------------------------------------- handlers
    async def version(self, _: Request):
        return JSONResponse({"version": "0.34.2"})

    async def tags(self, _: Request):
        return JSONResponse({"models": MODELS})

    async def show(self, request: Request):
        name = (await request.json())["model"]
        for m in MODELS:
            if m["name"] == name:
                return JSONResponse({"capabilities": m["capabilities"], "details": m["details"]})
        return JSONResponse({"error": f"model '{name}' not found"}, status_code=404)

    async def ps(self, _: Request):
        return JSONResponse(
            {"models": [{"name": n, "size": 5_000_000_000, "size_vram": 5_000_000_000} for n in sorted(self.loaded)]}
        )

    def _chunks(self, model: str, messages: list[dict]) -> list[dict]:
        user = messages[-1]["content"]
        if messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
            names = [ln[2:].split(":")[0] for ln in user.split("CRITERIA:")[1].splitlines() if ln.startswith("- ")]
            scores = {n: {"score": self.judge_scores.get(model, 4), "reason": f"scored by {model}"} for n in names}
            return make_stream(json.dumps({"scores": scores}))
        if user.startswith("Reply with the single word"):
            return make_stream("OK", eval_count=1, load_duration_ns=2_000_000_000)
        if "What is 2+3" in user and model == "qwen3:8b":
            return load_fixture("chat_stream_think.ndjson")  # real recorded stream (cold start, thinking)
        if "What is 2+3" in user:
            return make_stream("Final answer: 6")
        if "exactly one of these labels" in user:
            return make_stream(self.classification[model])
        return make_stream("Rain taps the glass, soft and slow; the grey sky sighs.")

    async def chat(self, request: Request):
        body = await request.json()
        self.requests.append(body)
        model = body["model"]
        if body.get("keep_alive") == 0 and not body.get("messages"):
            self.loaded.discard(model)
            return JSONResponse({"model": model, "done": True, "done_reason": "unload"})
        self.loaded.add(model)
        chunks = self._chunks(model, body["messages"])

        async def gen():
            for c in chunks:
                await asyncio.sleep(0.001)
                yield (json.dumps(c) + "\n").encode()

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    # ---------------------------------------------------------------- lifecycle
    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/api/version", self.version),
                Route("/api/tags", self.tags),
                Route("/api/show", self.show, methods=["POST"]),
                Route("/api/ps", self.ps),
                Route("/api/chat", self.chat, methods=["POST"]),
            ]
        )

    def start(self) -> str:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        config = uvicorn.Config(self.app(), host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake Ollama did not start")
            time.sleep(0.02)
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)


@contextlib.contextmanager
def running_fake_ollama() -> Iterator[tuple[FakeOllamaServer, str]]:
    srv = FakeOllamaServer()
    url = srv.start()
    try:
        yield srv, url
    finally:
        srv.stop()
