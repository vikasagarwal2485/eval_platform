"""Client SDK deployed agents use to stream their interactions into the eval platform (design D3).

Design goal: the platform must never slow down or break the agent (proposal.md - "Stream interactions in").
Events are queued in memory and sent from a background thread; under sustained backpressure the *oldest* queued
events are dropped rather than blocking the agent's own response path. Only `httpx` is required.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

__all__ = ["AgentClient", "Turn"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class Turn:
    """One turn of a conversation. Use as a context manager via `AgentClient.turn(...)`."""

    def __init__(self, client: AgentClient, session_id: str, turn_id: str, input_text: str, reference: str | None):
        self._client = client
        self.session_id = session_id
        self.turn_id = turn_id
        self._output = ""
        self._error: str | None = None
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
            }
        )

    def __enter__(self) -> Turn:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "error" if exc is not None else "ok"
        if exc is not None:
            self._error = str(exc)
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
    ) -> None:
        """Records one LLM call as a span. `model` is required: a span without it is never eligible to be
        evaluated (spec `trace-ingestion`)."""
        now = _now_iso()
        self._client._emit(
            {
                "v": 1,
                "event_id": _new_id(),
                "ts": now,
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "type": "span",
                "span_id": _new_id(),
                "kind": "llm",
                "model": model,
                "messages": messages or [],
                "output": output,
                "thinking": thinking,
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
                "ttft_ms": ttft_ms,
                "started_at": started_at or now,
                "ended_at": ended_at or now,
                "error": error,
            }
        )

    def tool_call(
        self,
        *,
        name: str,
        args: dict | None = None,
        result: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        error: str | None = None,
    ) -> None:
        now = _now_iso()
        self._client._emit(
            {
                "v": 1,
                "event_id": _new_id(),
                "ts": now,
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "type": "span",
                "span_id": _new_id(),
                "kind": "tool",
                "name": name,
                "args": args or {},
                "result": result,
                "started_at": started_at or now,
                "ended_at": ended_at or now,
                "error": error,
            }
        )


class AgentClient:
    """Queues events and sends them from a background thread. Never blocks or raises into the agent's own code."""

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
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="eval-agent-sdk", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ public surface
    def turn(self, session_id: str, *, input: str, reference: str | None = None, turn_id: str | None = None) -> Turn:
        return Turn(self, session_id, turn_id or _new_id(), input, reference)

    def close(self, timeout_s: float = 5.0) -> None:
        """Flushes what it can within `timeout_s`, then stops the background thread."""
        deadline = time.monotonic() + timeout_s
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._client.close()

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
