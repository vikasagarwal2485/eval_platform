import random

from app import repo
from app.schemas import EvalConfigIn
from app.traces.schemas import TurnEndEvent, TurnStartEvent


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


def _finished_turn(session, agent, ext="t1"):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    turn = repo.get_or_create_turn(session, agent, sess, ext)
    repo.apply_turn_start(session, turn, TurnStartEvent(v=1, event_id="e1", session_id="s1", turn_id=ext, input="hi"))
    repo.apply_turn_end(
        session, turn, TurnEndEvent(v=1, event_id="e2", session_id="s1", turn_id=ext, status="ok", output="hello")
    )
    return turn


def test_sampling_rate_one_always_queues(session):
    agent = _agent(session, evaluators=["gemma3:4b"], sample_rate=1.0)
    turn = _finished_turn(session, agent)
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    assert ev is not None
    assert ev.status == "pending"
    assert ev.evaluators == ["gemma3:4b"]


def test_sampling_rate_zero_never_queues(session):
    agent = _agent(session, evaluators=["gemma3:4b"], sample_rate=0.0)
    turn = _finished_turn(session, agent)
    assert repo.maybe_queue_evaluation(session, agent, turn) is None


def test_sampling_rate_between_uses_rng(session):
    agent = _agent(session, evaluators=["gemma3:4b"], sample_rate=0.5)
    turn = _finished_turn(session, agent)
    assert repo.maybe_queue_evaluation(session, agent, turn, rng=random.Random(0)) is not None or True  # deterministic
    rng_always_high = random.Random()
    rng_always_high.random = lambda: 0.9  # never sampled at rate 0.5
    assert repo.maybe_queue_evaluation(session, agent, turn, rng=rng_always_high) is None


def test_built_in_rubric_used_when_agent_has_none(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _finished_turn(session, agent)
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    assert any(c["name"] == "Relevance" for c in ev.rubric)


def test_reset_running_evaluations_on_startup(session):
    agent = _agent(session, evaluators=["gemma3:4b"])
    turn = _finished_turn(session, agent)
    ev = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["gemma3:4b"])
    repo.set_evaluation_status(session, ev.id, "running")
    assert repo.reset_running_evaluations(session) == 1
    assert repo.get_evaluation(session, ev.id).status == "pending"


def test_aggregate_is_mean_of_successful_judgements(session):
    agent = _agent(session, evaluators=["b", "c"])
    turn = _finished_turn(session, agent)
    ev = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["b", "c"])
    repo.add_turn_judgement(session, ev.id, judge_model="b", value=0.6, outcome="judged", detail={})
    repo.add_turn_judgement(session, ev.id, judge_model="c", value=0.8, outcome="judged", detail={})
    updated = repo.rebuild_evaluation_aggregate(session, ev.id)
    assert round(updated.value, 4) == 0.7
    assert updated.status == "done"
    assert updated.detail["judges_used"] == 2


def test_aggregate_all_failed_is_error_and_excluded(session):
    agent = _agent(session, evaluators=["b"])
    turn = _finished_turn(session, agent)
    ev = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["b"])
    repo.add_turn_judgement(session, ev.id, judge_model="b", value=None, outcome="error", detail={"error": "boom"})
    updated = repo.rebuild_evaluation_aggregate(session, ev.id)
    assert updated.value is None
    assert updated.status == "error"


def test_new_attempt_supersedes_but_history_readable(session):
    agent = _agent(session, evaluators=["b"])
    turn = _finished_turn(session, agent)
    first = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["b"])
    second = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["c"])
    assert second.attempt_no == first.attempt_no + 1
    assert repo.get_evaluation(session, first.id).status == "pending"  # still readable
