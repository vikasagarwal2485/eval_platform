from app import repo
from app.core.eval_context import BUILTIN_RUBRICS, build_context, resolve_rubric, turn_response_text
from app.schemas import EvalConfigIn, RubricCriterionIn
from app.traces.schemas import SpanEvent, TurnEndEvent, TurnStartEvent


def _agent(session, kind="chatbot", rubric=None):
    agent, _ = repo.create_agent(
        session, name="bot", kind=kind, declared_model="qwen3:8b", eval_config=EvalConfigIn(), rubric=rubric
    )
    return agent


def _turn(session, agent, ext, text_in, text_out):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    turn = repo.get_or_create_turn(session, agent, sess, ext)
    repo.apply_turn_start(session, turn, TurnStartEvent(v=1, event_id="a", session_id="s1", turn_id=ext, input=text_in))
    repo.apply_turn_end(
        session, turn, TurnEndEvent(v=1, event_id="b", session_id="s1", turn_id=ext, status="ok", output=text_out)
    )
    return turn


def test_built_in_rubric_by_kind(session):
    chatbot = _agent(session, kind="chatbot")
    assert resolve_rubric(chatbot) == BUILTIN_RUBRICS["chatbot"]


def test_custom_rubric_overrides_built_in(session):
    custom = [RubricCriterionIn(name="Brevity", description="Short").model_dump()]
    agent = _agent(session, rubric=custom)
    assert resolve_rubric(agent) == custom


def test_rubric_edit_does_not_change_already_snapshotted_evaluation(session):
    agent = _agent(session)
    turn = _turn(session, agent, "t1", "hi", "hello")
    ev = repo.maybe_queue_evaluation(session, agent, turn)
    original_rubric = ev.rubric
    agent.rubric = [{"name": "Only", "description": "one"}]
    session.flush()
    assert repo.get_evaluation(session, ev.id).rubric == original_rubric


def test_build_context_includes_prior_turns_and_current_input(session):
    agent = _agent(session)
    t1 = _turn(session, agent, "t1", "first question", "first answer")
    t2 = _turn(session, agent, "t2", "second question", "")
    ctx = build_context(t2, [t1], context_turns=4)
    assert "first question" in ctx and "first answer" in ctx and "second question" in ctx


def test_build_context_truncates_to_budget(session):
    agent = _agent(session)
    t1 = _turn(session, agent, "t1", "x" * 5000, "y" * 5000)
    t2 = _turn(session, agent, "t2", "current", "")
    ctx = build_context(t2, [t1], context_turns=4, char_budget=200)
    assert len(ctx) <= 200 + len("current") + 20
    assert "current" in ctx


def test_turn_response_text_includes_thinking_for_multi_span_turns(session):
    agent = _agent(session, kind="reasoning")
    turn = _turn(session, agent, "t1", "solve", "42")
    repo.apply_span(
        session,
        turn,
        SpanEvent(
            v=1, event_id="s1", session_id="s1", turn_id="t1", span_id="sp1", kind="llm", model="qwen3:8b",
            thinking="step one, step two",
        ),
    )
    text = turn_response_text(turn)
    assert "step one" in text and text.endswith("42")
