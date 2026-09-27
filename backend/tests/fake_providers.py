"""Fake OpenAI and Anthropic HTTP servers for tests (no keys, no network).

They stream the providers' documented SSE formats (OpenAI Chat Completions with `stream_options.include_usage`;
Anthropic Messages events), authenticate with an expected key, capture every request (including headers), and can be
scripted per request: rate limits with Retry-After, overload, auth failure, errors mid-stream, truncated streams.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


@dataclass
class Step:
    """One scripted reaction to the next chat request. Default (empty script) is a normal answer."""

    kind: str = "ok"  # ok | status | midstream_error | truncate | slow
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: dict | None = None
    text: str | None = None  # answer text for ok
    thinking: str | None = None
    usage: dict | None = None
    model: str | None = None
    delay_s: float = 0.0


def _find_schema_names(schema: dict) -> list[str]:
    try:
        return list(schema["properties"]["scores"]["properties"])
    except (KeyError, TypeError):
        return []


def _sse(event: str | None, data: dict | str) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data)
    return (f"event: {event}\n" if event else "").encode() + f"data: {payload}\n\n".encode()


class _Base:
    kind = "base"
    expected_key = "test-key-123"
    default_model = "m"

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.script: deque[Step] = deque()
        self.answer = "Hello from the fake provider"
        self.models: list[str] = []
        self.judge_score = 4
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    # ---- helpers
    def chat_requests(self) -> list[dict]:
        return [r for r in self.requests if r["path"] in self.chat_paths]

    async def _record(self, request: Request) -> dict:
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        rec = {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
        }
        self.requests.append(rec)
        return rec

    def _authed(self, rec: dict) -> bool:
        raise NotImplementedError

    def _next_step(self) -> Step:
        return self.script.popleft() if self.script else Step()

    def _error_response(self, step: Step) -> Response:
        return JSONResponse(step.body or self.error_body(step.status), status_code=step.status, headers=step.headers)

    # ---- lifecycle
    def app(self) -> Starlette:
        raise NotImplementedError

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
                raise RuntimeError(f"fake {self.kind} did not start")
            time.sleep(0.02)
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)


class FakeOpenAI(_Base):
    kind = "openai"
    chat_paths = ("/v1/chat/completions",)
    default_model = "gpt-4o-2024-08-06"

    def __init__(self) -> None:
        super().__init__()
        self.models = ["gpt-4o", "gpt-4o-mini", "o3"]

    def error_body(self, status: int) -> dict:
        msgs = {
            401: "Incorrect API key provided: sk-proj-***",
            429: "Rate limit reached for requests",
            503: "The server is overloaded or not ready yet.",
        }
        return {"error": {"message": msgs.get(status, "error"), "type": "invalid_request_error", "code": None}}

    def _authed(self, rec: dict) -> bool:
        return rec["headers"].get("authorization") == f"Bearer {self.expected_key}"

    async def list_models(self, request: Request):
        rec = await self._record(request)
        if not self._authed(rec):
            return JSONResponse(self.error_body(401), status_code=401)
        return JSONResponse(
            {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "openai"} for m in self.models]}
        )

    async def chat(self, request: Request):
        rec = await self._record(request)
        if not self._authed(rec):
            return JSONResponse(self.error_body(401), status_code=401)
        step = self._next_step()
        if step.kind == "status":
            return self._error_response(step)
        body = rec["body"] or {}
        structured = body.get("response_format", {}).get("type") == "json_schema"
        if structured:
            names = _find_schema_names(body["response_format"]["json_schema"]["schema"])
            text = step.text or json.dumps(
                {"scores": {n: {"score": self.judge_score, "reason": "fine"} for n in names}}
            )
        else:
            text = step.text or self.answer
        usage = step.usage or {
            "prompt_tokens": 21,
            "completion_tokens": max(1, len(text.split())),
            "total_tokens": 0,
            "completion_tokens_details": {"reasoning_tokens": 0},
        }
        model = step.model or self.default_model

        async def gen():
            def chunk(delta, finish=None, usage_=None, choices=True):
                d = {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}] if choices else [],
                }
                if usage_ is not None:
                    d["usage"] = usage_
                return _sse(None, d)

            if step.delay_s:
                await asyncio.sleep(step.delay_s)
            yield chunk({"role": "assistant", "content": ""})
            words = text.split(" ")
            for i, w in enumerate(words):
                yield chunk({"content": w + (" " if i < len(words) - 1 else "")})
                if step.kind == "midstream_error" and i == 0:
                    yield _sse(
                        None,
                        {
                            "error": {
                                "message": "The server had an error while processing your request",
                                "type": "server_error",
                            }
                        },
                    )
                    return
                if step.kind == "truncate" and i == 0:
                    return
            yield chunk({}, finish="stop")
            if body.get("stream_options", {}).get("include_usage"):
                yield chunk({}, usage_=usage, choices=False)
            yield _sse(None, "[DONE]")

        return StreamingResponse(gen(), media_type="text/event-stream")

    def app(self) -> Starlette:
        return Starlette(
            routes=[Route("/v1/models", self.list_models), Route("/v1/chat/completions", self.chat, methods=["POST"])]
        )


class FakeAnthropic(_Base):
    kind = "anthropic"
    chat_paths = ("/v1/messages",)
    default_model = "claude-sonnet-4-20250514"

    def __init__(self) -> None:
        super().__init__()
        self.models = ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"]

    def error_body(self, status: int) -> dict:
        types = {
            401: ("authentication_error", "invalid x-api-key"),
            429: ("rate_limit_error", "rate limited"),
            529: ("overloaded_error", "Overloaded"),
            500: ("api_error", "Internal server error"),
        }
        t, m = types.get(status, ("api_error", "error"))
        return {"type": "error", "error": {"type": t, "message": m}}

    def _authed(self, rec: dict) -> bool:
        return rec["headers"].get("x-api-key") == self.expected_key and "anthropic-version" in rec["headers"]

    async def list_models(self, request: Request):
        rec = await self._record(request)
        if not self._authed(rec):
            return JSONResponse(self.error_body(401), status_code=401)
        data = [
            {
                "type": "model",
                "id": m,
                "display_name": m.replace("-", " ").title(),
                "created_at": "2025-01-01T00:00:00Z",
            }
            for m in self.models
        ]
        return JSONResponse({"data": data, "has_more": False, "first_id": data[0]["id"] if data else None})

    async def messages(self, request: Request):
        rec = await self._record(request)
        if not self._authed(rec):
            return JSONResponse(self.error_body(401), status_code=401)
        step = self._next_step()
        if step.kind == "status":
            return self._error_response(step)
        body = rec["body"] or {}
        forced_tool = (body.get("tool_choice") or {}).get("name")
        thinking_on = (body.get("thinking") or {}).get("type") in ("enabled", "adaptive")
        model = step.model or self.default_model
        in_tokens = (step.usage or {}).get("input_tokens", 25)
        out_tokens = (step.usage or {}).get("output_tokens")

        if forced_tool:
            schema = next((t["input_schema"] for t in body.get("tools", []) if t["name"] == forced_tool), {})
            names = _find_schema_names(schema)
            text = step.text or json.dumps(
                {"scores": {n: {"score": self.judge_score, "reason": "fine"} for n in names}}
            )
        else:
            text = step.text or self.answer
        if out_tokens is None:
            out_tokens = max(1, len(text.split()))

        async def gen():
            if step.delay_s:
                await asyncio.sleep(step.delay_s)
            yield _sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": in_tokens, "output_tokens": 1},
                    },
                },
            )
            index = 0
            if thinking_on:
                thought = step.thinking or "Let me think about this."
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "thinking_delta", "thinking": thought},
                    },
                )
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "signature_delta", "signature": "sig"},
                    },
                )
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
                index += 1
            if forced_tool:
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "tool_use", "id": "toolu_1", "name": forced_tool, "input": {}},
                    },
                )
                half = len(text) // 2
                for part in (text[:half], text[half:]):
                    yield _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "input_json_delta", "partial_json": part},
                        },
                    )
            else:
                yield _sse(
                    "content_block_start",
                    {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
                )
                words = text.split(" ")
                for i, w in enumerate(words):
                    yield _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "text_delta", "text": w + (" " if i < len(words) - 1 else "")},
                        },
                    )
                    if step.kind == "midstream_error" and i == 0:
                        yield _sse(
                            "error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
                        )
                        return
                    if step.kind == "truncate" and i == 0:
                        return
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
            yield _sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use" if forced_tool else "end_turn", "stop_sequence": None},
                    "usage": {
                        "output_tokens": out_tokens,
                        **(
                            {"output_tokens_details": step.usage["output_tokens_details"]}
                            if step.usage and "output_tokens_details" in step.usage
                            else {}
                        ),
                    },
                },
            )
            yield _sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(gen(), media_type="text/event-stream")

    def app(self) -> Starlette:
        return Starlette(
            routes=[Route("/v1/models", self.list_models), Route("/v1/messages", self.messages, methods=["POST"])]
        )
