from datetime import timedelta

from app import repo
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import TurnEndEvent, TurnStartEvent


def _agent(session, **eval_kwargs):
    agent, _ = repo.create_agent(
        session, name="bot", kind="reasoning", declared_model="qwen3:8b", eval_config=EvalConfigIn(**eval_kwargs),
        rubric=None,
    )
    return agent


def _turn(session, agent, ext, *, reference=None, output="5", quiet_seconds=100):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    turn = repo.get_or_create_turn(session, agent, sess, ext)
    repo.apply_turn_start(
        session, turn, TurnStartEvent(v=1, event_id=f"{ext}s", session_id="s1", turn_id=ext, input="2+3?", reference=reference)
    )
    repo.apply_turn_end(
        session, turn, TurnEndEvent(v=1, event_id=f"{ext}e", session_id="s1", turn_id=ext, status="ok", output=output)
    )
    turn.ended_at = utcnow() - timedelta(seconds=quiet_seconds)
    session.flush()
    return turn


def test_reference_supplied_gives_separate_correctness_result(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _turn(session, agent, "t1", reference="5", output="Final answer: 5")
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    assert ev.reference_result is not None
    assert ev.reference_result["outcome"] == "correct"
    assert ev.value is None  # the judged score is separate and not yet computed


def test_no_reference_means_no_reference_result(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _turn(session, agent, "t1", reference=None, output="Final answer: 5")
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    assert ev.reference_result is None


def test_wrong_reference_answer_is_recorded_as_wrong(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _turn(session, agent, "t1", reference="5", output="Final answer: 6")
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    assert ev.reference_result["outcome"] == "wrong"


def test_reevaluate_single_turn_creates_a_new_attempt(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _turn(session, agent, "t1")
    first = repo.maybe_queue_evaluation(session, agent, turn)
    second = repo.reevaluate_turn(session, turn, evaluators=["other:1"])
    assert second.attempt_no == first.attempt_no + 1
    assert second.evaluators == ["other:1"]
    assert repo.get_evaluation(session, first.id).status == "pending"  # original still readable


def test_bulk_reevaluate_by_threshold(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    low = _turn(session, agent, "low")
    high = _turn(session, agent, "high")
    ev_low = repo.create_pending_evaluation(session, low, rubric=[], evaluators=["gemma3:4b"])
    repo.add_turn_judgement(session, ev_low.id, judge_model="gemma3:4b", value=0.2, outcome="judged", detail={})
    repo.rebuild_evaluation_aggregate(session, ev_low.id)
    ev_high = repo.create_pending_evaluation(session, high, rubric=[], evaluators=["gemma3:4b"])
    repo.add_turn_judgement(session, ev_high.id, judge_model="gemma3:4b", value=0.9, outcome="judged", detail={})
    repo.rebuild_evaluation_aggregate(session, ev_high.id)

    queued = repo.reevaluate_agent_turns(session, agent, below_score=0.5)
    assert {e.turn_id for e in queued} == {low.id}


def test_bulk_reevaluate_by_window(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    old = _turn(session, agent, "old", quiet_seconds=10_000)
    recent = _turn(session, agent, "recent", quiet_seconds=10)
    cutoff = utcnow() - timedelta(seconds=1000)
    queued = repo.reevaluate_agent_turns(session, agent, since=cutoff)
    assert {e.turn_id for e in queued} == {recent.id}
    assert old.id not in {e.turn_id for e in queued}
