import asyncio
import json

from app import repo
from app.core.eval_worker import EvaluationWorker
from app.core.model_discovery import ModelDiscovery
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import SpanEvent, TurnEndEvent, TurnStartEvent
from tests.fakes import FakeOllama, make_stream, make_tag


def _judge_reply(score: int = 4):
    scores = {
        name: {"score": score, "reason": "ok"}
        for name in ("Relevance", "Helpfulness", "Coherence", "Tone and safety")
    }
    return json.dumps({"scores": scores})


class _StubRouter:
    """A thin, router-shaped wrapper around FakeOllama for local-only evaluator tests."""

    def __init__(self, fake: FakeOllama):
        self.fake = fake

    def chat_stream(self, **kw):
        return self.fake.chat_stream(**kw)

    async def unload(self, name):
        await self.fake.unload(name)

    def preflight(self, refs):
        return []

    def model_info(self, ref):
        return None


def _agent(session, **eval_kwargs):
    agent, _ = repo.create_agent(
        session, name="bot", kind="chatbot", declared_model="author:1", eval_config=EvalConfigIn(**eval_kwargs),
        rubric=None,
    )
    return agent


def _closed_turn(session, agent, ext="t1", author="author:1", quiet_seconds=100):
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    turn = repo.get_or_create_turn(session, agent, sess, ext)
    repo.apply_turn_start(session, turn, TurnStartEvent(v=1, event_id=f"{ext}s", session_id="s1", turn_id=ext, input="hi"))
    repo.apply_span(
        session, turn,
        SpanEvent(v=1, event_id=f"{ext}sp", session_id="s1", turn_id=ext, span_id="sp1", kind="llm", model=author, output="hello"),
    )
    repo.apply_turn_end(
        session, turn, TurnEndEvent(v=1, event_id=f"{ext}e", session_id="s1", turn_id=ext, status="ok", output="hello")
    )
    turn.ended_at = utcnow() - __import__("datetime").timedelta(seconds=quiet_seconds)
    session.flush()
    return turn


def _make_responder(reply=_judge_reply):
    def responder(model, messages, options):
        if messages and messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
            return make_stream(reply())
        return make_stream("ok")

    return responder


def test_quiet_turn_is_evaluated(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=5)
        turn = _closed_turn(session, agent, quiet_seconds=100)
        session.commit()
        ev = repo.maybe_queue_evaluation(session, agent, turn)
        session.commit()
        ev_id = ev.id

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1
    with session_factory() as session:
        ev = repo.get_evaluation(session, ev_id)
        assert ev.status == "done"
        assert round(ev.value, 4) == 0.75  # a score of 4/5 on every criterion normalizes to (4-1)/4


def test_within_quiet_period_is_deferred(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=1000)
        turn = _closed_turn(session, agent, quiet_seconds=1)  # ended just now, well within a 1000s quiet period
        session.commit()
        repo.maybe_queue_evaluation(session, agent, turn)
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 0
    with session_factory() as session:
        pending = repo.list_pending_evaluations(session)
        assert len(pending) == 1  # still waiting, not skipped or errored


def test_a_continuously_active_agent_still_gets_its_finished_turns_evaluated(session_factory, settings):
    """Regression: ingest touches `agent.last_seen_at` on every call, including a brand new turn's `turn.start`.
    A chatbot mid-conversation is *always* recently seen - if that alone blocked evaluation, an agent that never
    goes quiet would never be evaluated at all, defeating the point of evaluating live traffic. Only an actually
    in-flight (open) turn should defer evaluation, not mere recent activity."""
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=5)
        old_turn = _closed_turn(session, agent, ext="old", quiet_seconds=100)
        session.commit()
        repo.maybe_queue_evaluation(session, agent, old_turn)
        session.commit()
        # the agent is mid-conversation: it just started a brand new turn, so it was "seen" moments ago
        repo.touch_agent_liveness(session, agent)
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1  # the older, already-quiet turn is still evaluated


def test_evaluation_defers_only_while_the_agent_has_a_turn_actually_in_flight(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=5)
        old_turn = _closed_turn(session, agent, ext="old", quiet_seconds=100)
        session.commit()
        repo.maybe_queue_evaluation(session, agent, old_turn)
        # a second turn is still open (its turn.start arrived, no turn.end yet)
        sess = repo.get_or_create_agent_session(session, agent, "s1")
        repo.get_or_create_turn(session, agent, sess, "open-turn")
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 0  # deferred while a request is actually in flight

    with session_factory() as session:
        turn = repo.get_turn(session, repo.list_turns(session, agent.id, status="open")[0].id)
        repo.apply_turn_end(
            session, turn, TurnEndEvent(v=1, event_id="e", session_id="s1", turn_id="open-turn", status="ok", output="done")
        )
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1  # released once nothing is in flight any more


def test_benchmark_run_defers_evaluation_and_a_later_tick_processes_it(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    measuring = {"value": True}
    worker = EvaluationWorker(
        session_factory, _StubRouter(fake), ModelDiscovery(fake), is_measuring=lambda: measuring["value"]
    )
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=1)
        turn = _closed_turn(session, agent, quiet_seconds=100)
        session.commit()
        repo.maybe_queue_evaluation(session, agent, turn)
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.deferred_measuring is True
    assert stats.evaluated == 0
    measuring["value"] = False
    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1


def test_batched_by_evaluator_loads_each_evaluator_once(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("j1"), make_tag("j2")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["j1", "j2"], quiet_period_s=1)
        for i in range(3):
            turn = _closed_turn(session, agent, ext=f"t{i}", quiet_seconds=100)
            session.commit()
            repo.maybe_queue_evaluation(session, agent, turn)
        session.commit()

    asyncio.run(worker.tick())
    unload_order = [c[1] for c in fake.calls if c[0] == "unload"]
    chat_order = [c[1] for c in fake.calls if c[0] == "chat"]
    # every j1 chat call happens before any j2 chat call (grouped, one load per evaluator)
    first_j2 = chat_order.index("j2")
    assert all(m != "j2" for m in chat_order[:first_j2])
    assert unload_order == ["j1"]  # j1 unloaded before j2's group; no trailing unload needed


def test_backlog_cap_skips_the_oldest_excess(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake), backlog_cap=1)
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=3600)  # never becomes "ready" in this test
        for i in range(3):
            turn = _closed_turn(session, agent, ext=f"t{i}", quiet_seconds=1)
            session.commit()
            repo.maybe_queue_evaluation(session, agent, turn)
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.backlog_skipped == 2
    with session_factory() as session:
        pending = repo.list_pending_evaluations(session)
        assert len(pending) == 1


def test_evaluator_unreachable_mid_batch_keeps_earlier_judgements_and_retries_the_rest(session_factory, settings):
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _make_responder())
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))
    with session_factory() as session:
        agent = _agent(session, evaluators=["judge:1"], quiet_period_s=1)
        t_ok = _closed_turn(session, agent, ext="ok", quiet_seconds=100)
        session.commit()
        repo.maybe_queue_evaluation(session, agent, t_ok)
        t_fail = _closed_turn(session, agent, ext="fail", quiet_seconds=100)
        session.commit()
        ev_fail = repo.maybe_queue_evaluation(session, agent, t_fail)
        session.commit()
        ev_fail_id = ev_fail.id

    # After the first (successful) call, the connection drops for the rest of this tick.
    from app.ollama.client import OllamaUnreachable

    calls = {"n": 0}
    real_responder = fake.responder

    def flaky(model, messages, options):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OllamaUnreachable("dropped")
        return real_responder(model, messages, options)

    fake.responder = flaky
    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1  # the first one got judged before the connection dropped
    with session_factory() as session:
        ev = repo.get_evaluation(session, ev_fail_id)
        assert ev.status == "pending"  # reverted, not stuck at "running", for the next tick to retry

    fake.responder = real_responder
    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1
    with session_factory() as session:
        assert repo.get_evaluation(session, ev_fail_id).status == "done"
