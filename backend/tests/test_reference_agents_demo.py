"""Task 7.2: the documented demonstration setup (agent on one model, evaluator on a different one) actually
produces evaluated turns with no self-judged score - exercised with the exact event shapes the reference agents
emit (proven byte-for-byte in test_reference_agents.py) run through the real ingest and evaluation path."""

import asyncio

from app import repo
from app.core.eval_worker import EvaluationWorker
from app.core.model_discovery import ModelDiscovery
from app.models import utcnow
from app.schemas import EvalConfigIn
from app.traces.schemas import SpanEvent, TurnEndEvent, TurnStartEvent
from tests.fakes import FakeOllama, make_stream, make_tag


def _judge_reply():
    import json

    names = ["Relevance", "Helpfulness", "Coherence", "Tone and safety"]
    return json.dumps({"scores": {n: {"score": 5, "reason": "great"} for n in names}})


def _responder(model, messages, options):
    if messages and messages[0]["role"] == "system" and "impartial evaluator" in messages[0]["content"]:
        return make_stream(_judge_reply())
    return make_stream("unused")


class _StubRouter:
    def __init__(self, fake):
        self.fake = fake

    def chat_stream(self, **kw):
        return self.fake.chat_stream(**kw)

    async def unload(self, name):
        await self.fake.unload(name)

    def preflight(self, refs):
        return []

    def model_info(self, ref):
        return None


def test_demo_setup_produces_an_evaluated_turn_with_no_self_judging(session_factory):
    """Mirrors the documented demo (agents/README.md): register a reference agent declaring one model, configure
    an evaluator that is a *different* model, run the agent (here: the exact events chatbot.py's `answer()` sends,
    per test_reference_agents.py), then let the evaluation worker score it."""
    fake = FakeOllama([make_tag("author:1"), make_tag("judge:1")], _responder)
    worker = EvaluationWorker(session_factory, _StubRouter(fake), ModelDiscovery(fake))

    with session_factory() as session:
        agent, _token = repo.create_agent(
            session,
            name="demo-chatbot",
            kind="chatbot",
            declared_model="author:1",
            eval_config=EvalConfigIn(evaluators=["judge:1"], quiet_period_s=0),
            rubric=None,
        )
        session.commit()

        sess = repo.get_or_create_agent_session(session, agent, "s1")
        turn = repo.get_or_create_turn(session, agent, sess, "t1")
        repo.apply_turn_start(session, turn, TurnStartEvent(v=1, event_id="e1", session_id="s1", turn_id="t1", input="hi"))
        repo.apply_span(
            session, turn,
            SpanEvent(v=1, event_id="e2", session_id="s1", turn_id="t1", span_id="sp1", kind="llm", model="author:1", output="Hello there!"),
        )
        repo.apply_turn_end(
            session, turn, TurnEndEvent(v=1, event_id="e3", session_id="s1", turn_id="t1", status="ok", output="Hello there!")
        )
        turn.ended_at = utcnow()  # quiet_period_s=0, so this is immediately ready
        session.commit()
        eval_id = repo.maybe_queue_evaluation(session, agent, turn).id
        session.commit()

    stats = asyncio.run(worker.tick())
    assert stats.evaluated == 1

    with session_factory() as session:
        ev = repo.get_evaluation(session, eval_id)
        assert ev.status == "done"
        assert ev.value is not None
        assert ev.detail.get("self_judged") is False
        judgements = repo.list_turn_judgements(session, ev.id)
        assert judgements[0].judge_model == "judge:1"  # scored by the evaluator, never by "author:1"
