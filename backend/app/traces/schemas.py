"""The v1 event contract agents stream in (design D2, spec `trace-ingestion`).

Two event types (`turn.start`, `turn.end`) reconstruct a conversation's evaluation-relevant summary
(add-otel-tracing: the third type, `span`, is retired - full span/call detail now goes straight to
Tempo via the agent's own OpenTelemetry instrumentation, never through this ingest; `turn.end`
reports the turn's `models`, token totals, `cost` and `trace_id` directly instead of the backend
deriving them from aggregated spans). Validation here is per-event and tolerant: an unknown
*version* fails the whole batch (the platform cannot safely interpret it), but a single malformed
event - including an event of the now-unrecognized `span` type - only rejects that event, reported
by its index, and oversized text is truncated rather than rejected. Unknown extra fields are
ignored so a newer SDK keeps working against an older platform.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_VERSIONS = (1,)
MAX_TEXT_CHARS = 20_000
MAX_EVENTS_PER_BATCH = 500
TRUNCATION_MARKER = "\n...[truncated]"


class UnsupportedSchemaVersion(ValueError):
    def __init__(self, version: Any):
        super().__init__(f"unsupported event schema version: {version!r}")
        self.version = version


def _truncate(text: str | None) -> tuple[str, bool]:
    if not text or len(text) <= MAX_TEXT_CHARS:
        return text or "", False
    return text[:MAX_TEXT_CHARS] + TRUNCATION_MARKER, True


class _Event(BaseModel):
    """Fields common to every event. Unknown fields are ignored, not rejected (forward compatibility)."""

    model_config = ConfigDict(extra="ignore")

    v: int
    event_id: str = Field(min_length=1, max_length=200)
    ts: str = ""
    session_id: str = Field(min_length=1, max_length=200)
    turn_id: str = Field(min_length=1, max_length=200)

    @field_validator("v")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v not in SUPPORTED_VERSIONS:
            raise UnsupportedSchemaVersion(v)
        return v


class TurnStartEvent(_Event):
    type: Literal["turn.start"] = "turn.start"
    input: str = ""
    reference: str | None = None
    metadata: dict = Field(default_factory=dict)
    # The system prompt actually in effect for this turn (after any skill instructions were
    # prepended), whether this turn was launched from a terminal or the platform's own Playground -
    # `None` only for an agent that genuinely sends no system message at all, never omitted just
    # because it's the agent's own hardcoded default rather than an operator override
    # (`add-agent-playground`).
    system_prompt: str | None = None

    def truncated(self) -> tuple[TurnStartEvent, bool]:
        text, cut1 = _truncate(self.input)
        system_prompt, cut2 = (None, False) if self.system_prompt is None else _truncate(self.system_prompt)
        return self.model_copy(update={"input": text, "system_prompt": system_prompt}), (cut1 or cut2)


class TurnEndEvent(_Event):
    type: Literal["turn.end"] = "turn.end"
    status: Literal["ok", "error"] = "ok"
    output: str = ""
    error: str | None = None
    # add-otel-tracing: the SDK reports these directly - it already held the per-call usage it was
    # instrumenting, and no `span` event survives for the backend to derive them from aggregating.
    models: list[str] = Field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None
    trace_id: str | None = None
    # the turn's reasoning trace (assembled by the SDK from its own calls' thinking output) - fed to
    # judge calls alongside `output`, same role the retired `span` events' `thinking` fields played
    thinking: str | None = None

    def truncated(self) -> tuple[TurnEndEvent, bool]:
        out, cut1 = _truncate(self.output)
        think, cut2 = _truncate(self.thinking)
        return self.model_copy(update={"output": out, "thinking": think or None}), (cut1 or cut2)


Event = Annotated[TurnStartEvent | TurnEndEvent, Field(discriminator="type")]

_BY_TYPE: dict[str, type[_Event]] = {
    "turn.start": TurnStartEvent,
    "turn.end": TurnEndEvent,
}


class Rejected(BaseModel):
    index: int
    reason: str


class BatchValidation(BaseModel):
    accepted: list[Event]
    was_truncated: list[bool]  # parallel to `accepted`: whether that event's text was cut
    rejected: list[Rejected]

    @property
    def truncated_count(self) -> int:
        return sum(self.was_truncated)


def validate_batch(raw_events: list[Any]) -> BatchValidation:
    """Parse and validate a batch. Raises `UnsupportedSchemaVersion` for the whole batch; individual malformed
    events are collected in `rejected` instead of raising."""
    if len(raw_events) > MAX_EVENTS_PER_BATCH:
        raise ValueError(f"batch exceeds the maximum of {MAX_EVENTS_PER_BATCH} events")
    accepted: list[Event] = []
    was_truncated: list[bool] = []
    rejected: list[Rejected] = []
    for i, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            rejected.append(Rejected(index=i, reason="event must be a JSON object"))
            continue
        v = raw.get("v")
        if v not in SUPPORTED_VERSIONS:
            raise UnsupportedSchemaVersion(v)
        type_ = raw.get("type")
        model = _BY_TYPE.get(type_)
        if model is None:
            rejected.append(Rejected(index=i, reason=f"unknown event type {type_!r}"))
            continue
        try:
            parsed = model.model_validate(raw)
        except UnsupportedSchemaVersion:
            raise
        except Exception as exc:  # pydantic ValidationError and friends
            rejected.append(Rejected(index=i, reason=str(exc).splitlines()[0]))
            continue
        cut_parsed, cut = parsed.truncated()
        accepted.append(cut_parsed)
        was_truncated.append(cut)
    return BatchValidation(accepted=accepted, was_truncated=was_truncated, rejected=rejected)
