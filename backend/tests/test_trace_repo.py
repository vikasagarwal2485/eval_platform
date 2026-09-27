from datetime import timedelta

from app import repo
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import SpanEvent, TurnEndEvent, TurnStartEvent


def _agent(session, **eval_kwargs):
    agent, _ = repo.create_agent(
        session,
        name="bot",
        kind="chatbot",
        declared_model="qwen3:8b",
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


def _span(**over):
    base = {
        "v": 1,
        "event_id": "e2",
        "session_id": "s1",
        "turn_id": "t1",
        "span_id": "sp1",
        "kind": "llm",
        "model": "qwen3:8b",
        "output": "hello",
    }
    return SpanEvent.model_validate({**base, **over})


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


def test_turn_reconstructed_from_start_span_end(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_turn_start(session, turn, _start())
    repo.apply_span(session, turn, _span())
    repo.apply_turn_end(session, turn, _end())
    assert turn.input == "hi"
    assert turn.output == "hello"
    assert turn.status == "ok"
    assert turn.models == ["qwen3:8b"]
    assert len(turn.spans) == 1


def test_replay_causes_no_duplication(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    assert repo.apply_turn_start(session, turn, _start()) is False
    assert repo.apply_turn_start(session, turn, _start()) is True  # duplicate
    assert repo.apply_span(session, turn, _span()) is False
    assert repo.apply_span(session, turn, _span()) is True  # duplicate
    assert repo.apply_turn_end(session, turn, _end()) is False
    assert repo.apply_turn_end(session, turn, _end()) is True  # duplicate
    assert len(turn.spans) == 1


def test_turn_end_before_start_creates_and_closes_the_turn(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_turn_end(session, turn, _end())
    assert turn.status == "ok"
    assert turn.input == ""  # not yet known
    repo.apply_turn_start(session, turn, _start())
    assert turn.input == "hi"  # filled in without creating a second turn
    assert turn.status == "ok"  # still closed


def test_llm_span_without_model_flags_unknown(session):
    agent = _agent(session)
    turn = _turn(session, agent)
    repo.apply_span(session, turn, _span(model=None, span_id="sp2"))
    assert turn.models_unknown is True
    assert turn.models == []


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
