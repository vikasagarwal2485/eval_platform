from datetime import timedelta

from app import repo
from app.core.agent_summary import build_agent_summary, list_needs_attention
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import TurnEndEvent, TurnStartEvent


def _agent(session, **kw):
    agent, _ = repo.create_agent(
        session, name="bot", kind="chatbot", declared_model="qwen3:8b", eval_config=EvalConfigIn(**kw), rubric=None
    )
    return agent


def _turn(session, agent, ext, *, status="ok", latency_ms=100.0, value=None, skip_reason=None):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    turn = repo.get_or_create_turn(session, agent, sess, ext)
    repo.apply_turn_start(session, turn, TurnStartEvent(v=1, event_id=f"{ext}s", session_id="s1", turn_id=ext, input="hi"))
    repo.apply_turn_end(
        session, turn, TurnEndEvent(v=1, event_id=f"{ext}e", session_id="s1", turn_id=ext, status=status, output="hello")
    )
    turn.latency_ms = latency_ms
    session.flush()
    if status == "ok":
        ev = repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["judge:1"])
        if value is not None:
            repo.add_turn_judgement(session, ev.id, judge_model="judge:1", value=value, outcome="judged", detail={})
            repo.rebuild_evaluation_aggregate(session, ev.id)
        elif skip_reason is not None:
            repo.set_evaluation_status(session, ev.id, "skipped", skip_reason=skip_reason)
    return turn


def test_empty_agent_has_no_evaluated_turns_and_no_crash(session):
    agent = _agent(session)
    summary = build_agent_summary(session, agent)
    assert summary["turns"]["total"] == 0
    assert summary["quality"]["mean"] is None
    assert summary["latency_ms"]["p50"] is None
    assert summary["error_rate"] is None


def test_turn_counts_and_error_rate(session):
    agent = _agent(session)
    _turn(session, agent, "ok1", status="ok", value=0.8)
    _turn(session, agent, "err1", status="error")
    summary = build_agent_summary(session, agent)
    assert summary["turns"]["total"] == 2
    assert summary["turns"]["ok"] == 1
    assert summary["turns"]["error"] == 1
    assert summary["error_rate"] == 0.5


def test_quality_mean_and_below_threshold(session):
    agent = _agent(session, attention_threshold=0.5)
    _turn(session, agent, "hi", value=0.9)
    _turn(session, agent, "lo", value=0.2)
    summary = build_agent_summary(session, agent)
    assert summary["quality"]["evaluated"] == 2
    assert round(summary["quality"]["mean"], 2) == 0.55
    assert summary["quality"]["below_threshold"] == 1


def test_latency_percentiles(session):
    agent = _agent(session)
    for i, ms in enumerate([100, 200, 300, 400]):
        _turn(session, agent, f"t{i}", latency_ms=ms, value=0.5)
    summary = build_agent_summary(session, agent)
    assert summary["latency_ms"]["p50"] in (200, 300)
    assert summary["latency_ms"]["p95"] == 400


def test_evaluator_strictness(session):
    agent = _agent(session)
    turn = _turn(session, agent, "t1", status="ok")
    evaluation = repo.get_evaluation(
        session, repo.create_pending_evaluation(session, turn, rubric=[], evaluators=["a", "b"]).id
    )
    repo.add_turn_judgement(session, evaluation.id, judge_model="a", value=0.9, outcome="judged", detail={})
    repo.add_turn_judgement(session, evaluation.id, judge_model="b", value=None, outcome="error", detail={})
    repo.rebuild_evaluation_aggregate(session, evaluation.id)
    summary = build_agent_summary(session, agent)
    by_model = {e["model"]: e for e in summary["evaluators"]}
    assert by_model["a"]["mean_score"] == 0.9
    assert by_model["b"]["errors"] == 1


def test_backlog_by_reason(session):
    agent = _agent(session)
    _turn(session, agent, "t1", skip_reason="no_eligible_evaluator")
    _turn(session, agent, "t2", skip_reason="no_eligible_evaluator")
    summary = build_agent_summary(session, agent)
    assert summary["backlog"]["skipped"] == {"no_eligible_evaluator": 2}


def test_window_excludes_old_turns(session):
    agent = _agent(session)
    turn = _turn(session, agent, "old", value=0.9)
    turn.ended_at = utcnow() - timedelta(days=30)
    session.flush()
    summary = build_agent_summary(session, agent, window="24h")
    assert summary["turns"]["total"] == 0


def test_needs_attention_lists_low_scores_only(session):
    agent = _agent(session, attention_threshold=0.5)
    _turn(session, agent, "good", value=0.9)
    _turn(session, agent, "bad", value=0.1)
    attention = list_needs_attention(session, agent)
    assert len(attention) == 1
    assert attention[0]["value"] == 0.1
