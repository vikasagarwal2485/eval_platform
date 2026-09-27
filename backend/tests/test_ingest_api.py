from app import repo
from app.schemas import EvalConfigIn
from tests.fakes import FakeOllama
from tests.helpers import new_client


def _make_agent(session_factory, **eval_kwargs) -> tuple[int, str]:
    with session_factory() as session:
        agent, raw = repo.create_agent(
            session,
            name="bot",
            kind="chatbot",
            declared_model="qwen3:8b",
            eval_config=EvalConfigIn(**eval_kwargs),
            rubric=None,
        )
        session.commit()
        return agent.id, raw


def _events(turn_id="t1"):
    return [
        {"v": 1, "event_id": "e1", "session_id": "s1", "turn_id": turn_id, "type": "turn.start", "input": "hi"},
        {
            "v": 1,
            "event_id": "e2",
            "session_id": "s1",
            "turn_id": turn_id,
            "type": "span",
            "span_id": "sp1",
            "kind": "llm",
            "model": "qwen3:8b",
            "output": "hello",
        },
        {
            "v": 1,
            "event_id": "e3",
            "session_id": "s1",
            "turn_id": turn_id,
            "type": "turn.end",
            "status": "ok",
            "output": "hello",
        },
    ]


def test_batch_accepted_and_stored(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"accepted": 3, "duplicates": 0, "rejected": []}
    with file_session_factory() as session:
        turns = repo.list_turns(session, agent_id)
        assert len(turns) == 1
        assert turns[0].status == "ok"
        assert repo.get_agent(session, agent_id).last_seen_at is not None


def test_retried_batch_is_all_duplicates(settings, file_session_factory):
    _, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        assert r.json() == {"accepted": 0, "duplicates": 3, "rejected": []}


def test_partial_batch_rejection_reports_index(settings, file_session_factory):
    _, token = _make_agent(file_session_factory)
    events = _events()
    bad = dict(events[1])
    del bad["kind"]
    batch = [events[0], bad, events[2]]
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=batch, headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        assert body["accepted"] == 2
        assert body["rejected"] == [{"index": 1, "reason": body["rejected"][0]["reason"]}]


def test_unauthorized_without_valid_token(settings, file_session_factory):
    _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        r = c.post("/api/ingest/v1/events", json=_events())
        assert r.status_code == 401


def test_paused_agent_rejects_ingest(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with file_session_factory() as session:
        repo.set_agent_status(session, agent_id, "paused")
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "agent_paused"


def test_unsampled_turn_is_not_queued_for_evaluation(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory, evaluators=["gemma3:4b"], sample_rate=0.0)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
    with file_session_factory() as session:
        turn = repo.list_turns(session, agent_id)[0]
        assert repo.get_evaluation.__module__  # sanity that repo import works
        from app.models import TurnEvaluation

        assert session.query(TurnEvaluation).filter(TurnEvaluation.turn_id == turn.id).count() == 0
