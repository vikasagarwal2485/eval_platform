"""Client SDK deployed agents use to stream their interactions into the eval platform (design D3).

Design goal: the platform must never slow down or break the agent (proposal.md - "Stream interactions in").
`turn.start`/`turn.end` events are queued in memory and sent from a background thread; under sustained
backpressure the *oldest* queued events are dropped rather than blocking the agent's own response path.

add-otel-tracing: `Turn.llm_call()`/`Turn.tool_call()` no longer send a `span` event over that same channel
(the `span` event type is retired) - they emit a real OpenTelemetry span instead, exported via OTLP straight
to the observability stack's Collector, never through the platform's own ingest. `turn.end` still carries the
turn's lightweight summary (`models`, token totals, cost, its reasoning trace, and the OTel `trace_id` that
ties it to its full span tree) - this summary channel is always on, independent of whether OTel tracing is
configured or Tempo is reachable (`trace-observability`: evaluation never depends on either).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode, set_span_in_context

from eval_agent_sdk.tracing import (
    EVAL_COST,
    EVAL_ERROR,
    EVAL_KIND,
    EVAL_REASONING_TOKENS_APPROX,
    GEN_AI_AGENT_DESCRIPTION,
    GEN_AI_AGENT_ID,
    GEN_AI_AGENT_NAME,
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_DESCRIPTION,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_USAGE_REASONING_OUTPUT_TOKENS,
    GEN_AI_WORKFLOW_NAME,
    compute_cost,
    setup_tracing,
)

__all__ = ["AgentClient", "Turn", "whoami"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_ns() -> int:
    return time.time_ns()


def _iso_to_ns(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1e9)
    except ValueError:
        return _now_ns()  # a malformed timestamp never blocks span creation - "now" is a safe fallback


def _new_id() -> str:
    return uuid.uuid4().hex


def _status_for(error: str | None) -> Status:
    return Status(StatusCode.ERROR, error) if error else Status(StatusCode.OK)


class Turn:
    """One turn of a conversation. Use as a context manager via `AgentClient.turn(...)`.

    When the client is configured for tracing, the turn gets one real OpenTelemetry trace: a root
    span for the turn itself, with one child span per `llm_call()`/`tool_call()`, each carrying its
    own timing and (for an LLM call) GenAI attributes and computed cost. Models/token totals/cost/
    reasoning trace are also accumulated in Python regardless - these always reach `turn.end`, with
    or without tracing configured (`trace-observability`: evaluation never depends on it)."""

    def __init__(
        self,
        client: AgentClient,
        session_id: str,
        turn_id: str,
        input_text: str,
        reference: str | None,
        system_prompt: str | None = None,
    ):
        self._client = client
        self.session_id = session_id
        self.turn_id = turn_id
        self._output = ""
        self._error: str | None = None
        self._models: list[str] = []
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None
        self._cost: float | None = None
        self._thinking_parts: list[str] = []
        self.trace_id: str | None = None
        self._root_span = None
        self._root_ctx = None

        provider = client._tracer_provider
        if provider is not None:
            tracer = provider.get_tracer("eval_agent_sdk")
            self._root_span = tracer.start_span("agent.turn", start_time=_now_ns(), kind=SpanKind.INTERNAL)
            self._root_span.set_attribute("session.id", session_id)
            self._root_span.set_attribute("turn.id", turn_id)
            # GenAI semconv's agent-identity attributes - set once per turn from whatever the client
            # was given at construction (never fabricated: omitted entirely when the client wasn't
            # told its own name/id/description, e.g. this platform's own `whoami()` currently reports
            # no agent id, so an agent relying only on that has no `gen_ai.agent.id` here either).
            if client._agent_name is not None:
                self._root_span.set_attribute(GEN_AI_AGENT_NAME, client._agent_name)
            if client._agent_id is not None:
                self._root_span.set_attribute(GEN_AI_AGENT_ID, client._agent_id)
            if client._agent_description is not None:
                self._root_span.set_attribute(GEN_AI_AGENT_DESCRIPTION, client._agent_description)
            # `gen_ai.workflow.name` + `gen_ai.operation.name="invoke_workflow"` - only when the
            # client was actually given a workflow name (e.g. reasoning_agent.py's fixed pipeline,
            # classifier_router_agent.py's real LangGraph graph); never fabricated for a turn that's
            # just a single call (chatbot.py never sets this).
            if client._workflow_name is not None:
                self._root_span.set_attribute(GEN_AI_OPERATION_NAME, "invoke_workflow")
                self._root_span.set_attribute(GEN_AI_WORKFLOW_NAME, client._workflow_name)
            self._root_ctx = set_span_in_context(self._root_span)
            ctx = self._root_span.get_span_context()
            self.trace_id = format(ctx.trace_id, "032x") if ctx.trace_id else None

        client._emit(
            {
                "v": 1,
                "event_id": _new_id(),
                "ts": _now_iso(),
                "session_id": session_id,
                "turn_id": turn_id,
                "type": "turn.start",
                "input": input_text,
                "reference": reference,
                "system_prompt": system_prompt,
            }
        )

    def __enter__(self) -> Turn:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "error" if exc is not None else "ok"
        if exc is not None:
            self._error = str(exc)
        if self._root_span is not None:
            self._root_span.set_status(_status_for(self._error))
            self._root_span.end(end_time=_now_ns())
        self._client._emit(
            {
                "v": 1,
                "event_id": _new_id(),
                "ts": _now_iso(),
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "type": "turn.end",
                "status": status,
                "output": self._output,
                "error": self._error,
                # add-otel-tracing: reported directly - the SDK already held this while instrumenting
                "models": self._models,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "cost": self._cost,
                "thinking": "\n\n".join(self._thinking_parts) if self._thinking_parts else None,
                "trace_id": self.trace_id,
            }
        )
        return False  # never swallow the agent's own exception

    def finish(self, output: str) -> None:
        """Records the turn's final output shown to the user. The `turn.end` event is sent when the `with`
        block exits, so this may be called any time before that."""
        self._output = output

    def llm_call(
        self,
        *,
        model: str,
        messages: list[dict] | None = None,
        output: str = "",
        thinking: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        ttft_ms: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        error: str | None = None,
        kind: str | None = None,
    ) -> None:
        """Records one LLM call. `model` is required: a turn with no models reported is never eligible to be
        evaluated (spec `trace-ingestion`). Emits a real OpenTelemetry span (GenAI semantic-convention
        attributes plus computed cost) when tracing is configured; always folds this call into the turn's
        own `models`/token totals/cost/reasoning trace, reported on `turn.end` regardless.

        Every call also gets `gen_ai.operation.name` = "chat" (this is always what this method
        represents, so it's set unconditionally, never from a caller-supplied value) - the correct
        standard attribute for "this span is a chat completion", as distinct from an embedding, a
        retrieval, a tool execution, and so on.

        `kind`: the call's role in this turn (e.g. "classify"/"plan"/"solve"/"verify"/"routing") -
        every call shares the same span name ("gen_ai.chat") *and* the same `gen_ai.operation.name`
        ("chat", since GenAI semconv's own enum has no finer-grained value than that), so without
        `kind` there is no way to tell which call was for what when a turn makes more than one.
        Recorded as `eval.kind`, not a `gen_ai.*` name - GenAI semconv has nothing that covers an
        agent's own task labels (`eval.kind` matches this span's own `eval.cost`/`eval.ttft_ms`
        below rather than inventing a non-standard `gen_ai.*` name). Omitted (the default) when the
        caller has nothing meaningful to put there - never fabricated.

        When `thinking` and `completion_tokens` are both given, also records
        `gen_ai.usage.reasoning.output_tokens` - the portion of `completion_tokens` spent on
        reasoning. No provider this SDK's reference callers use ever reports that count directly
        (Ollama, directly or via the gateway, only ever returns separate *text*, not a token
        count), so it is apportioned from `thinking`'s share of `thinking + output`'s combined
        character length and paired with `eval.reasoning_tokens_approx = true` so the estimate is
        never presented as a provider-reported fact - mirrors the Runner's own identical
        approximation (`app/core/metrics.py`'s `thinking_tokens`/`thinking_tokens_approx`)."""
        now = _now_iso()
        started_at, ended_at = started_at or now, ended_at or now
        cost = compute_cost(model, prompt_tokens, completion_tokens)

        reasoning_tokens: int | None = None
        if thinking and completion_tokens is not None:
            total_chars = len(thinking) + len(output)
            if total_chars > 0:
                reasoning_tokens = round(completion_tokens * len(thinking) / total_chars)

        if model and model not in self._models:
            self._models.append(model)
        if prompt_tokens is not None:
            self._prompt_tokens = (self._prompt_tokens or 0) + prompt_tokens
        if completion_tokens is not None:
            self._completion_tokens = (self._completion_tokens or 0) + completion_tokens
        if cost is not None:
            self._cost = (self._cost or 0.0) + cost
        if thinking:
            self._thinking_parts.append(thinking)

        if self._root_span is not None:
            tracer = self._client._tracer_provider.get_tracer("eval_agent_sdk")
            span = tracer.start_span(
                "gen_ai.chat", context=self._root_ctx, start_time=_iso_to_ns(started_at), kind=SpanKind.CLIENT
            )
            span.set_attribute(GEN_AI_OPERATION_NAME, "chat")
            span.set_attribute(GEN_AI_REQUEST_MODEL, model)
            if prompt_tokens is not None:
                span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, prompt_tokens)
            if completion_tokens is not None:
                span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, completion_tokens)
            if reasoning_tokens is not None:
                span.set_attribute(GEN_AI_USAGE_REASONING_OUTPUT_TOKENS, reasoning_tokens)
                span.set_attribute(EVAL_REASONING_TOKENS_APPROX, True)
            if cost is not None:
                span.set_attribute(EVAL_COST, cost)
            if ttft_ms is not None:
                span.set_attribute("eval.ttft_ms", ttft_ms)
            if kind is not None:
                span.set_attribute(EVAL_KIND, kind)
            span.set_status(_status_for(error))
            span.end(end_time=_iso_to_ns(ended_at))

    def tool_call(
        self,
        *,
        name: str,
        args: dict | None = None,
        result: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        error: str | None = None,
        model: str | None = None,
        description: str | None = None,
        call_id: str | None = None,
        tool_type: str = "function",
    ) -> None:
        """Records one tool call. GenAI semconv's own tool-call attributes (name, arguments, result,
        description, call id, type) rather than this SDK's earlier ad hoc `tool.*` names - unlike
        `eval.kind` (see `tracing.py`), the spec genuinely defines these. Also sets
        `gen_ai.operation.name` = "execute_tool" unconditionally (this is always what this method
        represents). A no-op span-wise when tracing isn't configured (nothing to fold into
        `turn.end`'s summary either: tool calls aren't part of the model/token/cost totals).

        `model`: optional - some "tools" are themselves backed by a specific model or service (e.g. an
        external classifier), and naming it here (as the same `gen_ai.request.model` attribute
        `llm_call()` uses, not a different key) lets one query find every span about that model
        regardless of whether it went through `llm_call()` or `tool_call()`. Omitted when there is no
        single model/service to name - never fabricated. `description`/`call_id` are likewise omitted
        unless the caller actually has one. `tool_type` defaults to "function" (the conventional value
        for a structured name/args/result call like this - GenAI semconv defines the attribute but not
        a closed set of values); pass a different one if a tool genuinely isn't that shape."""
        if self._root_span is None:
            return
        now = _now_iso()
        started_at, ended_at = started_at or now, ended_at or now
        tracer = self._client._tracer_provider.get_tracer("eval_agent_sdk")
        span = tracer.start_span(name, context=self._root_ctx, start_time=_iso_to_ns(started_at), kind=SpanKind.CLIENT)
        span.set_attribute(GEN_AI_OPERATION_NAME, "execute_tool")
        span.set_attribute(GEN_AI_TOOL_NAME, name)
        span.set_attribute(GEN_AI_TOOL_TYPE, tool_type)
        if description is not None:
            span.set_attribute(GEN_AI_TOOL_DESCRIPTION, description)
        if call_id is not None:
            span.set_attribute(GEN_AI_TOOL_CALL_ID, call_id)
        if args:
            span.set_attribute(GEN_AI_TOOL_CALL_ARGUMENTS, json.dumps(args, default=str))
        if result is not None:
            span.set_attribute(GEN_AI_TOOL_CALL_RESULT, result)
        if error:
            span.set_attribute(EVAL_ERROR, error)
        if model is not None:
            span.set_attribute(GEN_AI_REQUEST_MODEL, model)
        span.set_status(_status_for(error))
        span.end(end_time=_iso_to_ns(ended_at))


class AgentClient:
    """Queues `turn.start`/`turn.end` events and sends them from a background thread; never blocks or raises
    into the agent's own code. `Turn.llm_call()`/`Turn.tool_call()` export real OpenTelemetry spans directly
    to the Collector instead (add-otel-tracing) - this client only owns the tracer provider's lifecycle."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        batch_size: int = 20,
        flush_interval_s: float = 2.0,
        max_queue: int = 2000,
        timeout_s: float = 5.0,
        max_attempts: int = 3,
        backoff_s: float = 0.5,
        redact: Callable[[dict], dict] | None = None,
        transport: httpx.BaseTransport | None = None,
        otel_endpoint: str | None = None,
        service_name: str = "agent",
        tracer_provider: TracerProvider | None = None,
        agent_name: str | None = None,
        agent_id: str | None = None,
        agent_description: str | None = None,
        workflow_name: str | None = None,
    ):
        self._url = base_url.rstrip("/") + "/api/ingest/v1/events"
        self._token = token
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._max_attempts = max_attempts
        self._backoff_s = backoff_s
        self._redact = redact
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self.dropped = 0  # oldest-dropped counter, for observability
        self._client = httpx.Client(timeout=timeout_s, transport=transport)
        # Set once per turn's own root span as GenAI semconv's agent-identity attributes (Turn.__init__)
        # - never fabricated: each stays unset unless the caller actually knows it (e.g. this platform's
        # own `whoami()` currently reports an agent's `name` but no `id`/`description`).
        self._agent_name = agent_name
        self._agent_id = agent_id
        self._agent_description = agent_description
        # Set on a turn's own root span as `gen_ai.workflow.name` (+ `gen_ai.operation.name` -
        # Turn.__init__) only when this agent's own turn is actually a multi-step workflow - unset
        # for e.g. chatbot.py, whose turn is a single call, never fabricated as one.
        self._workflow_name = workflow_name
        # `tracer_provider` (for tests, or a caller that already owns one) is used as given, and never
        # shut down by this client - only a provider this client built itself from `otel_endpoint` is.
        self._owns_tracer_provider = tracer_provider is None
        self._tracer_provider = tracer_provider if tracer_provider is not None else setup_tracing(
            otel_endpoint, service_name=service_name
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="eval-agent-sdk", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ public surface
    def turn(
        self,
        session_id: str,
        *,
        input: str,
        reference: str | None = None,
        turn_id: str | None = None,
        system_prompt: str | None = None,
    ) -> Turn:
        return Turn(self, session_id, turn_id or _new_id(), input, reference, system_prompt)

    def close(self, timeout_s: float = 5.0) -> None:
        """Flushes what it can within `timeout_s`, then stops the background thread."""
        deadline = time.monotonic() + timeout_s
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._client.close()
        if self._owns_tracer_provider and self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            except Exception:  # noqa: BLE001 - shutting down telemetry must never raise into the agent
                pass

    # ------------------------------------------------------------------ internals
    def _emit(self, event: dict) -> None:
        if self._redact is not None:
            try:
                event = self._redact(event)
            except Exception:  # noqa: BLE001 - a broken redact hook must never break the agent
                pass
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        # Sustained backpressure: drop the oldest queued event and make room, never block the caller.
        try:
            self._queue.get_nowait()
            self.dropped += 1
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1  # lost the race with another producer thread; still never raises

    def _drain_batch(self) -> list[dict]:
        batch: list[dict] = []
        try:
            batch.append(self._queue.get(timeout=self._flush_interval_s))
        except queue.Empty:
            return batch
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _send(self, batch: list[dict]) -> None:
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(self._max_attempts):
            try:
                resp = self._client.post(self._url, json=batch, headers=headers)
                if resp.status_code < 500:
                    return  # 2xx/4xx: the platform has decided; retrying will not help for a 4xx either
            except httpx.HTTPError:
                pass
            if attempt + 1 < self._max_attempts:
                time.sleep(self._backoff_s * (2**attempt))
        # exhausted retries: the batch is dropped rather than blocking or growing the queue further

    def _run(self) -> None:
        while not self._stop.is_set():
            batch = self._drain_batch()
            if batch:
                self._send(batch)


def whoami(platform_url: str, token: str, *, timeout: float = 10.0) -> dict:
    """Reads this agent's own registration back from the platform (spec `agent-registry`, "An agent can
    discover its own registration", `add-agent-self-discovery`): `{"name", "kind", "declared_models",
    "gateway_model_groups"}` - the last one already computed by the platform, so a caller never needs to
    reimplement its slugging convention. Standalone, not a method on `AgentClient`: this is a one-time,
    must-succeed-or-fail-clearly call a caller makes once at startup (see design.md - "Decisions"), unlike
    `AgentClient`'s fire-and-forget background delivery - a failure here is the caller's to observe and act on
    (e.g. fall back to a hardcoded default and warn), not something to silently retry in the background. Raises
    `httpx.HTTPError` on a non-2xx response, a connection failure or a timeout; never swallows an error."""
    url = platform_url.rstrip("/") + "/api/ingest/v1/whoami"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
