"""OpenAI adapter: Chat Completions streaming, translated to Ollama-shaped chunks (design D5)."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.providers.cloud import CloudBackend, final_chunk, iter_sse, text_chunk
from app.providers.errors import ProviderError, ProviderUnavailable

_UNSUPPORTED = re.compile(r"Unsupported (?:parameter|value): '([A-Za-z_.]+)'")
DROPPABLE = {"temperature", "seed", "top_p"}  # optional sampling settings that some models reject


def unsupported_param(message: str) -> str | None:
    """The parameter name a 400 error complains about, e.g. `Unsupported parameter: 'seed'`."""
    m = _UNSUPPORTED.search(message or "")
    return m.group(1) if m else None


def strictify(schema: Any) -> Any:
    """Make a JSON schema acceptable to OpenAI strict structured output: every object gets
    `additionalProperties: false` and lists all its properties as required; unsupported range keywords are dropped
    (the judge validates ranges itself)."""
    schema = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"):
                node.pop(k, None)
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


class OpenAIBackend(CloudBackend):
    kind = "openai"
    default_base_url = "https://api.openai.com"

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"authorization": f"Bearer {key}"}

    @property
    def official(self) -> bool:
        """The official endpoint takes `max_completion_tokens` (needed by reasoning models); compatible gateways
        generally accept only `max_tokens`."""
        return self.cfg.base_url is None

    async def list_models(self) -> list[str]:
        data = await self.request_json("GET", "/v1/models")
        return sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m)

    def build_body(self, model, messages, options, think, format, reasoning) -> tuple[dict, dict, list[dict]]:
        """(request body, params applied, params ignored) - what was and was not honoured is recorded (spec)."""
        options = options or {}
        applied: dict[str, Any] = {}
        ignored: list[dict] = []
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if "temperature" in options:
            if reasoning:
                ignored.append(
                    {"name": "temperature", "reason": "reasoning models do not accept a temperature setting"}
                )
            else:
                body["temperature"] = options["temperature"]
                applied["temperature"] = options["temperature"]
        if "seed" in options:
            body["seed"] = options["seed"]
            applied["seed"] = options["seed"]
            applied["seed_note"] = "best effort; determinism is not guaranteed"
        if options.get("num_predict"):
            body["max_completion_tokens" if self.official else "max_tokens"] = options["num_predict"]
            applied["max_output_tokens"] = options["num_predict"]
        if options.get("num_ctx"):
            ignored.append({"name": "num_ctx", "reason": "context size is not configurable for this provider"})
        if think is not None:
            ignored.append(
                {"name": "think", "reason": "the provider does not expose a thinking switch or reasoning text"}
            )
        if isinstance(format, dict):
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "judge_scores", "strict": True, "schema": strictify(format)},
            }
            applied["structured_output"] = "json_schema"
        elif format == "json":
            body["response_format"] = {"type": "json_object"}
            applied["structured_output"] = "json_object"
        return body, applied, ignored

    def _adjust_for_rejection(self, exc: ProviderError, body: dict, applied: dict, ignored: list[dict]) -> bool:
        """React to a 400 that names an unsupported optional parameter: drop (or rename) it and record why.
        Returns True if the request was adjusted and should be retried."""
        if exc.status != 400:
            return False
        msg, param = str(exc), unsupported_param(str(exc))
        if param == "max_tokens" and "max_completion_tokens" in msg and "max_tokens" in body:
            body["max_completion_tokens"] = body.pop("max_tokens")  # the model wants the newer name
            ignored.append({"name": "max_tokens", "reason": "sent as max_completion_tokens as the model requires"})
            return True
        if param in DROPPABLE and param in body:
            body.pop(param)
            applied.pop(param, None)
            applied.pop(f"{param}_note", None)
            ignored.append({"name": param, "reason": f"rejected by the provider: {msg}"})
            return True
        return False

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
        body, applied, ignored = self.build_body(model, messages, options, think, format, reasoning)
        for _ in range(4):  # a model may reject several optional settings, one error at a time
            try:
                opened = await self.open_stream("POST", "/v1/chat/completions", json_body=body)
                break
            except ProviderError as exc:
                if not self._adjust_for_rejection(exc, body, applied, ignored):
                    raise
        else:  # pragma: no cover - loop ends only via break/raise
            raise ProviderUnavailable("too many rejected parameters", provider=self.cfg.name)
        resp = opened.response
        version, finish, usage, finished = None, None, None, False
        try:
            async for _, data in iter_sse(resp):
                if data == "[DONE]":
                    finished = True
                    break
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict) and ev.get("error"):
                    err = ev["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise ProviderUnavailable(self._clean(f"provider error mid-stream: {msg}"), provider=self.cfg.name)
                version = ev.get("model") or version
                if ev.get("usage"):
                    usage = ev["usage"]
                for choice in ev.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    thought = delta.get("reasoning_content") or ""  # some compatible gateways stream reasoning text
                    if content or thought:
                        yield text_chunk(content, thought)
                    finish = choice.get("finish_reason") or finish
            if not finished and not finish:
                raise ProviderUnavailable("stream ended before the answer was complete", provider=self.cfg.name)
        except ProviderError:
            raise
        except Exception as exc:  # transport failure while streaming
            raise ProviderUnavailable(self._clean(f"stream interrupted: {exc}"), provider=self.cfg.name) from exc
        finally:
            await resp.aclose()
        details = (usage or {}).get("completion_tokens_details") or (usage or {}).get("output_tokens_details") or {}
        yield final_chunk(
            done_reason=finish or "stop",
            prompt_tokens=(usage or {}).get("prompt_tokens"),
            output_tokens=(usage or {}).get("completion_tokens"),
            provider={
                "provider": self.cfg.name,
                "kind": self.kind,
                "model_version": version,
                "attempts": opened.attempts,
                "retry_wait_ms": opened.retry_wait_ms,
                "params_applied": applied,
                "params_ignored": ignored,
                "reasoning_tokens": details.get("reasoning_tokens"),
                "finish_reason": finish,
            },
        )
