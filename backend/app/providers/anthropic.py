"""Anthropic adapter: Messages API streaming, translated to Ollama-shaped chunks (design D6).

Checked against the current docs: usage in `message_delta` is cumulative, `ping` events may appear anywhere, errors
arrive as `event: error`, and thinking is model dependent - `thinking.type: "enabled"` (with `budget_tokens`) is
rejected by newer models, which use `adaptive` - so the adapter tries one and falls back to the other on that 400.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.providers.cloud import CloudBackend, final_chunk, iter_sse, text_chunk
from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)

API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096
MIN_THINKING_BUDGET = 1024
TOOL_NAME = "record_scores"

_STOP_TO_DONE = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "stop", "max_tokens": "length"}


def thinking_config(mode: str, max_tokens: int) -> dict | None:
    """The `thinking` request field for a mode, or None if it cannot be used at this token limit."""
    if mode == "adaptive":
        return {"type": "adaptive"}
    if max_tokens <= MIN_THINKING_BUDGET:
        return None  # the budget must be at least 1,024 and less than max_tokens
    return {"type": "enabled", "budget_tokens": min(max(MIN_THINKING_BUDGET, max_tokens // 2), max_tokens - 1)}


class AnthropicBackend(CloudBackend):
    kind = "anthropic"
    default_base_url = "https://api.anthropic.com"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thinking_mode: dict[str, str] = {}  # model -> mode that worked last time (enabled | adaptive)

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": API_VERSION}

    async def list_models(self) -> list[str]:
        ids: list[str] = []
        after = None
        for _ in range(10):  # paginated: follow `has_more` a bounded number of times
            path = "/v1/models?limit=1000" + (f"&after_id={after}" if after else "")
            data = await self.request_json("GET", path)
            page = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
            ids.extend(page)
            if not data.get("has_more") or not page:
                break
            after = page[-1]
        return sorted(ids)

    # ------------------------------------------------------------------ request
    def build_body(self, model, messages, options, think, format, reasoning, mode: str = "enabled"):
        options = options or {}
        applied: dict[str, Any] = {}
        ignored: list[dict] = []
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": options.get("num_predict") or DEFAULT_MAX_TOKENS,
            "messages": [m for m in messages if m["role"] != "system"],
            "stream": True,
        }
        if system:
            body["system"] = system
        applied["max_output_tokens"] = body["max_tokens"]

        thinking = None
        if think and reasoning:
            if format is not None:
                ignored.append(
                    {
                        "name": "think",
                        "reason": "thinking cannot be combined with a forced tool call (structured output)",
                    }
                )
            else:
                thinking = thinking_config(mode, body["max_tokens"])
                if thinking is None:
                    ignored.append(
                        {
                            "name": "think",
                            "reason": "max output tokens too low for a thinking budget (needs more than 1,024)",
                        }
                    )
        if thinking:
            body["thinking"] = thinking
            applied["thinking"] = thinking["type"] + (
                f" (budget {thinking['budget_tokens']})" if "budget_tokens" in thinking else ""
            )
        elif think and not reasoning:
            ignored.append({"name": "think", "reason": "the model is not flagged as a reasoning model"})

        if "temperature" in options:
            if thinking:
                ignored.append({"name": "temperature", "reason": "temperature cannot be set while thinking is enabled"})
            else:
                body["temperature"] = options["temperature"]
                applied["temperature"] = options["temperature"]
        if "seed" in options:
            ignored.append({"name": "seed", "reason": "this provider does not support a random seed"})
        if options.get("num_ctx"):
            ignored.append({"name": "num_ctx", "reason": "context size is not configurable for this provider"})

        if isinstance(format, dict):  # structured judge output: one forced tool call whose input is the JSON
            body["tools"] = [
                {"name": TOOL_NAME, "description": "Record the scores for the response.", "input_schema": format}
            ]
            body["tool_choice"] = {"type": "tool", "name": TOOL_NAME}
            applied["structured_output"] = "forced tool call"
        elif format == "json":
            ignored.append({"name": "format", "reason": "no plain JSON mode; the prompt asks for JSON instead"})
        return body, applied, ignored

    @staticmethod
    def _thinking_rejected(exc: ProviderError, mode: str) -> bool:
        msg = str(exc)
        return exc.status == 400 and f"thinking.type.{mode}" in msg and "not supported" in msg

    # ------------------------------------------------------------------ streaming
    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        think: bool | None = None,
        format: Any = None,
        keep_alive: Any = None,
        reasoning: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        mode = self._thinking_mode.get(model, "enabled")
        tried: list[str] = []
        while True:
            body, applied, ignored = self.build_body(model, messages, options, think, format, reasoning, mode)
            try:
                opened = await self.open_stream("POST", "/v1/messages", json_body=body)
                break
            except ProviderError as exc:
                tried.append(mode)
                other = "adaptive" if mode == "enabled" else "enabled"
                if "thinking" in body and self._thinking_rejected(exc, mode) and other not in tried:
                    mode = other  # newer models reject `enabled`, older ones reject `adaptive`
                    continue
                if "thinking" in body and self._thinking_rejected(exc, mode):
                    think = False  # neither mode is available for this model: run without thinking, and say so
                    continue
                raise
        if tried:
            if "thinking" in body:
                ignored.append(
                    {
                        "name": "thinking_mode",
                        "reason": f"'{tried[-1]}' was rejected by the model; used '{mode}' instead",
                    }
                )
            else:
                ignored.append({"name": "think", "reason": "the model accepts neither thinking mode"})
        if "thinking" in body:
            self._thinking_mode[model] = mode
        async for chunk in self._read(opened, applied, ignored, body):
            yield chunk

    async def _read(self, opened, applied, ignored, body) -> AsyncIterator[dict[str, Any]]:
        resp = opened.response
        version = stop = None
        in_tokens = out_tokens = thinking_tokens = None
        finished = False
        block_kind: dict[int, str] = {}
        try:
            async for event, data in iter_sse(resp):
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type") or event
                if kind == "ping":
                    continue
                if kind == "error":
                    raise self._stream_error(ev.get("error") or {})
                if kind == "message_start":
                    msg = ev.get("message") or {}
                    version = msg.get("model") or version
                    usage = msg.get("usage") or {}
                    in_tokens = (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0)
                    )
                    out_tokens = usage.get("output_tokens", out_tokens)
                elif kind == "content_block_start":
                    block_kind[ev.get("index", 0)] = (ev.get("content_block") or {}).get("type", "text")
                elif kind == "content_block_delta":
                    delta = ev.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta" and delta.get("text"):
                        yield text_chunk(delta["text"])
                    elif dtype == "thinking_delta" and delta.get("thinking"):
                        yield text_chunk("", delta["thinking"])
                    elif dtype == "input_json_delta" and delta.get("partial_json"):
                        yield text_chunk(delta["partial_json"])  # forced tool call: its input *is* the JSON answer
                    # signature_delta and citations are not part of the answer
                elif kind == "message_delta":
                    stop = (ev.get("delta") or {}).get("stop_reason") or stop
                    usage = ev.get("usage") or {}
                    out_tokens = usage.get("output_tokens", out_tokens)  # cumulative
                    if usage.get("input_tokens"):
                        in_tokens = usage["input_tokens"]
                    details = usage.get("output_tokens_details") or {}
                    thinking_tokens = details.get("thinking_tokens", thinking_tokens)
                elif kind == "message_stop":
                    finished = True
                    break
            if not finished:
                raise ProviderUnavailable("stream ended before the answer was complete", provider=self.cfg.name)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport failure while streaming
            raise ProviderUnavailable(self._clean(f"stream interrupted: {exc}"), provider=self.cfg.name) from exc
        finally:
            await resp.aclose()
        yield final_chunk(
            done_reason=_STOP_TO_DONE.get(stop or "end_turn", "stop"),
            prompt_tokens=in_tokens,
            output_tokens=out_tokens,
            provider={
                "provider": self.cfg.name,
                "kind": self.kind,
                "model_version": version,
                "attempts": opened.attempts,
                "retry_wait_ms": opened.retry_wait_ms,
                "params_applied": applied,
                "params_ignored": ignored,
                "reasoning_tokens": thinking_tokens,
                "finish_reason": stop,
            },
        )

    def _stream_error(self, err: dict) -> ProviderError:
        msg = self._clean(f"provider error mid-stream: {err.get('message') or err.get('type') or 'unknown'}")
        etype = err.get("type")
        if etype == "authentication_error" or etype == "permission_error":
            return ProviderAuthError(msg, provider=self.cfg.name)
        if etype == "rate_limit_error":
            return ProviderRateLimited(msg, provider=self.cfg.name)
        return ProviderUnavailable(msg, provider=self.cfg.name)
