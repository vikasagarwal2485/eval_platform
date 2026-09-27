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
    result = validate_batch([_turn_start(), _span(), _turn_end()])
    assert len(result.accepted) == 3
    assert result.rejected == []


def test_unknown_extra_fields_are_ignored():
    result = validate_batch([_turn_start(some_future_field="x")])
    assert len(result.accepted) == 1
    assert result.rejected == []


def test_unsupported_version_rejects_whole_batch():
    with pytest.raises(UnsupportedSchemaVersion):
        validate_batch([_turn_start(), _turn_end(v=99)])


def test_one_malformed_event_does_not_fail_the_batch():
    bad = _span()
    del bad["kind"]  # required field missing
    result = validate_batch([_turn_start(), bad, _turn_end()])
    assert len(result.accepted) == 2
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
    result = validate_batch([_turn_start(), {"v": 1, "event_id": "e9", "session_id": "s1", "turn_id": "t1", "type": "span.delta"}])
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1


def test_batch_too_large_is_rejected():
    with pytest.raises(ValueError):
        validate_batch([_turn_start()] * 501)
