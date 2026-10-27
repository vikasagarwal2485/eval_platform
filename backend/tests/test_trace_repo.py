from datetime import timedelta

from app import repo
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import TurnEndEvent, TurnStartEvent


def _agent(session, **eval_kwargs):
    agent, _ = repo.create_agent(
        session,
        name="bot",
        kind="chatbot",
        declared_models={"default": "qwen3:8b"},
        eval_config=EvalConfigIn(**eval_kwargs),
        rubric=None,
    )
    return agent


def _turn(session, agent):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    return repo.get_or_create_turn(session, agent, sess, "t1")


def _start(**over):
    base = {"v": 1, "event_id": "e1", "session_id": "s1", "turn_id": "t1", "input": "hi"}
    return TurnStartEvent.model_validate({**base, **over})


def _end(**over):
    base = {"v": 1, "event_id": "e3", "session_id": "s1", "turn_id": "t1", "status": "ok", "output": "hello"}
    return TurnEndEvent.model_validate({**base, **over})


def test_session_and_turn_are_idempotent(session):
    agent = _agent(session)
    s1 = repo.get_or_create_agent_session(session, agent, "s1")
    s2 = repo.get_or_create_agent_session(session, agent, "s1")
    assert s1.id == s2.id
    t1 = repo.get_or_create_turn(session, agent, s1, "t1")
    t2 = repo.get_or_create_turn(session, agent, s1, "t1")
    assert t1.id == t2.id


def test_turn_reconstructed_from_start_and_end(session):
    """add-otel-tracing: `turn.end` reports models/tokens/cost/trace_id directly - no `span` event
    for the backend to derive them from."""
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_turn_start(session, turn, _start())
    repo.apply_turn_end(
        session, turn, _end(models=["qwen3:8b"], prompt_tokens=20, completion_tokens=5, cost=0.001, trace_id="a" * 32)
    )
    assert turn.input == "hi"
    assert turn.output == "hello"
    assert turn.status == "ok"
    assert turn.models == ["qwen3:8b"]
    assert turn.prompt_tokens == 20 and turn.completion_tokens == 5
    assert turn.cost == 0.001
    assert turn.trace_id == "a" * 32


def test_replay_causes_no_duplication(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    assert repo.apply_turn_start(session, turn, _start()) is False
    assert repo.apply_turn_start(session, turn, _start()) is True  # duplicate
    assert repo.apply_turn_end(session, turn, _end()) is False
    assert repo.apply_turn_end(session, turn, _end()) is True  # duplicate


def test_turn_end_before_start_creates_and_closes_the_turn(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_turn_end(session, turn, _end())
    assert turn.status == "ok"
    assert turn.input == ""  # not yet known
    repo.apply_turn_start(session, turn, _start())
    assert turn.input == "hi"  # filled in without creating a second turn
    assert turn.status == "ok"  # still closed


def test_turn_end_arriving_in_a_separate_request_from_turn_start(session_factory):
    """Regression: a real agent sends `turn.start` immediately and `turn.end` only once its LLM call returns,
    so - unlike every test above - they arrive as *separate* ingest requests, each with its own session. Reading
    `turn.started_at` back fresh from SQLite (naive) and subtracting it from a same-request-parsed `ended_at`
    (aware) must not raise, or the whole `turn.end` batch 500s and the turn is stuck open forever."""
    with session_factory() as s1:
        agent = _agent(s1)
        turn = _turn(s1, agent)
        repo.apply_turn_start(s1, turn, _start())
        s1.commit()
        turn_id = turn.id

    # a brand new session, as a separate HTTP request would get via `Depends(get_session)`
    with session_factory() as s2:
        turn = repo.get_turn(s2, turn_id)
        repo.apply_turn_end(s2, turn, _end())  # must not raise TypeError (naive vs aware datetimes)
        s2.commit()

    with session_factory() as s3:
        turn = repo.get_turn(s3, turn_id)
        assert turn.status == "ok"
        assert turn.output == "hello"
        assert turn.latency_ms is not None and turn.latency_ms >= 0


def test_turn_end_with_no_models_reported_leaves_models_empty_and_unknown_false(session):
    """add-otel-tracing: no more per-span `models_unknown` derivation - an empty `models` list is
    itself the "don't assume safe to judge" signal eligibility already treats the same way."""
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_turn_end(session, turn, _end())  # omits `models` entirely
    assert turn.models == []
    assert turn.models_unknown is False


def test_abandoned_sweep_marks_stale_open_turns(session):
    agent = _agent(session, abandon_after_s=1)
    turn = _turn(session, agent)
    turn.started_at = utcnow() - timedelta(seconds=5)
    session.flush()
    abandoned = repo.sweep_abandoned_turns(session)
    assert [t.id for t in abandoned] == [turn.id]
    assert turn.status == "abandoned"


def test_abandoned_sweep_leaves_fresh_open_turns(session):
    agent = _agent(session, abandon_after_s=600)
    turn = _turn(session, agent)
    turn.started_at = utcnow()
    session.flush()
    assert repo.sweep_abandoned_turns(session) == []
    assert turn.status == "open"
