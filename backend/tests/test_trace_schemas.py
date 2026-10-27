import pytest

from app.traces.schemas import (
    MAX_TEXT_CHARS,
    UnsupportedSchemaVersion,
    validate_batch,
)


def _turn_start(**over):
    base = {"v": 1, "event_id": "e1", "session_id": "s1", "turn_id": "t1", "type": "turn.start", "input": "hi"}
    return {**base, **over}


def _span(**over):
    """add-otel-tracing: this event type is retired - now just an unrecognized event, same as any
    other unknown `type` (per spec `trace-ingestion`, "Malformed events are rejected individually")."""
    base = {
        "v": 1,
        "event_id": "e2",
        "session_id": "s1",
        "turn_id": "t1",
        "type": "span",
        "span_id": "sp1",
        "kind": "llm",
        "model": "qwen3:8b",
        "output": "hello",
    }
    return {**base, **over}


def _turn_end(**over):
    base = {"v": 1, "event_id": "e3", "session_id": "s1", "turn_id": "t1", "type": "turn.end", "status": "ok"}
    return {**base, **over}


def test_valid_batch_all_accepted():
    result = validate_batch([_turn_start(), _turn_end()])
    assert len(result.accepted) == 2
    assert result.rejected == []


def test_unknown_extra_fields_are_ignored():
    result = validate_batch([_turn_start(some_future_field="x")])
    assert len(result.accepted) == 1
    assert result.rejected == []


def test_unsupported_version_rejects_whole_batch():
    with pytest.raises(UnsupportedSchemaVersion):
        validate_batch([_turn_start(), _turn_end(v=99)])


def test_one_malformed_event_does_not_fail_the_batch():
    bad = _turn_end()
    bad["status"] = "not-a-valid-status"  # only "ok"/"error" are accepted
    result = validate_batch([_turn_start(), bad])
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].index == 1


def test_oversized_output_is_truncated_not_rejected():
    huge = "x" * (MAX_TEXT_CHARS + 500)
    result = validate_batch([_turn_end(output=huge)])
    assert len(result.accepted) == 1
    assert result.truncated_count == 1
    assert result.accepted[0].output.endswith("[truncated]")
    assert len(result.accepted[0].output) < len(huge)


def test_unknown_event_type_is_rejected_individually():
    result = validate_batch(
        [_turn_start(), {"v": 1, "event_id": "e9", "session_id": "s1", "turn_id": "t1", "type": "span.delta"}]
    )
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1


def test_span_event_only_that_event_is_rejected_turn_start_and_end_still_accepted():
    """add-otel-tracing 5.1: the retired `span` type is now just an unrecognized event type - only
    it is rejected, the surrounding turn.start/turn.end events in the same batch are unaffected."""
    result = validate_batch([_turn_start(), _span(), _turn_end()])
    assert [e.type for e in result.accepted] == ["turn.start", "turn.end"]
    assert len(result.rejected) == 1
    assert result.rejected[0].index == 1
    assert "span" in result.rejected[0].reason


def test_turn_end_reports_models_tokens_cost_and_trace_id_directly():
    """add-otel-tracing: no more deriving these from aggregated span events."""
    result = validate_batch(
        [
            _turn_end(
                models=["@oa/gpt-4o", "qwen3:8b"],
                prompt_tokens=120,
                completion_tokens=45,
                cost=0.0025,
                trace_id="a" * 32,
            )
        ]
    )
    (event,) = result.accepted
    assert event.models == ["@oa/gpt-4o", "qwen3:8b"]
    assert event.prompt_tokens == 120
    assert event.completion_tokens == 45
    assert event.cost == 0.0025
    assert event.trace_id == "a" * 32


def test_turn_end_new_fields_default_to_empty_or_none_when_omitted():
    (event,) = validate_batch([_turn_end()]).accepted
    assert event.models == []
    assert event.prompt_tokens is None
    assert event.completion_tokens is None
    assert event.cost is None
    assert event.trace_id is None


def test_batch_too_large_is_rejected():
    with pytest.raises(ValueError):
        validate_batch([_turn_start()] * 501)
