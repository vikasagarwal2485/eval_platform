from tests.fakes import FakeOllama
from tests.helpers import new_client


def _create_agent(c, **over):
    body = {"name": "bot", "kind": "chatbot", "declared_model": "author:1", **over}
    r = c.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ingest(c, token, events):
    return c.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})


def _turn_events(ext="t1", author="author:1"):
    return [
        {"v": 1, "event_id": f"{ext}s", "session_id": "s1", "turn_id": ext, "type": "turn.start", "input": "hi"},
        {
            "v": 1, "event_id": f"{ext}sp", "session_id": "s1", "turn_id": ext, "type": "span", "span_id": f"{ext}sp1",
            "kind": "llm", "model": author, "output": "hello",
        },
        {"v": 1, "event_id": f"{ext}e", "session_id": "s1", "turn_id": ext, "type": "turn.end", "status": "ok", "output": "hello"},
    ]


# ------------------------------------------------------------------ 5.1 registry
def test_create_list_get_agent(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        created = _create_agent(c)
        assert "token" in created and created["token"]
        r = c.get("/api/agents")
        assert r.status_code == 200 and len(r.json()) == 1
        r = c.get(f"/api/agents/{created['id']}")
        assert r.status_code == 200
        assert "token" not in r.json()


def test_duplicate_name_is_409(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c)
        r = c.post("/api/agents", json={"name": "bot", "kind": "chatbot", "declared_model": "x:1"})
        assert r.status_code == 409


def test_self_evaluator_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot", "kind": "chatbot", "declared_model": "author:1",
                "eval_config": {"evaluators": ["author:1"]},
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_settings"


def test_hosted_evaluator_requires_ack(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot", "kind": "chatbot", "declared_model": "author:1",
                "eval_config": {"evaluators": ["@openai-main/gpt-4o"]},
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        r = c.post(
            "/api/agents",
            json={
                "name": "bot", "kind": "chatbot", "declared_model": "author:1",
                "eval_config": {"evaluators": ["@openai-main/gpt-4o"]}, "provider_acks": ["openai-main"],
            },
        )
        assert r.status_code == 201


def test_update_settings_persists_and_re_validates(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        r = c.patch(f"/api/agents/{agent['id']}", json={"eval_config": {"evaluators": ["judge:1"]}})
        assert r.status_code == 200
        assert r.json()["eval_config"]["evaluators"] == ["judge:1"]
        r = c.patch(f"/api/agents/{agent['id']}", json={"eval_config": {"evaluators": ["author:1"]}})
        assert r.status_code == 422


def test_pause_resume_and_ingest_effect(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        c.post(f"/api/agents/{agent['id']}/pause")
        r = _ingest(c, agent["token"], _turn_events())
        assert r.status_code == 403
        c.post(f"/api/agents/{agent['id']}/resume")
        r = _ingest(c, agent["token"], _turn_events())
        assert r.status_code == 200


def test_rotate_token_invalidates_old(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        old_token = agent["token"]
        r = c.post(f"/api/agents/{agent['id']}/rotate-token")
        new_token = r.json()["token"]
        assert _ingest(c, old_token, _turn_events()).status_code == 401
        assert _ingest(c, new_token, _turn_events()).status_code == 200


def test_delete_agent(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        r = c.delete(f"/api/agents/{agent['id']}")
        assert r.status_code == 204
        assert c.get(f"/api/agents/{agent['id']}").status_code == 404


# ------------------------------------------------------------------ 5.2 turns
def test_list_and_get_turn(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        _ingest(c, agent["token"], _turn_events("t2"))
        r = c.get(f"/api/agents/{agent['id']}/turns")
        assert r.status_code == 200 and len(r.json()) == 2
        r = c.get(f"/api/agents/{agent['id']}/turns?status=ok&limit=1")
        assert len(r.json()) == 1
        turn_id = r.json()[0]["id"]
        detail = c.get(f"/api/agents/{agent['id']}/turns/{turn_id}").json()
        assert detail["spans"][0]["model"] == "author:1"
        assert "evaluations" in detail


def test_turn_from_another_agent_is_404(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        a1 = _create_agent(c, name="a1")
        a2 = _create_agent(c, name="a2")
        _ingest(c, a1["token"], _turn_events("t1"))
        turn_id = c.get(f"/api/agents/{a1['id']}/turns").json()[0]["id"]
        assert c.get(f"/api/agents/{a2['id']}/turns/{turn_id}").status_code == 404


# ------------------------------------------------------------------ 5.3 summary / attention
def test_summary_and_attention_endpoints(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        r = c.get(f"/api/agents/{agent['id']}/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["turns"]["total"] == 1
        r2 = c.get(f"/api/agents/{agent['id']}/attention")
        assert r2.status_code == 200 and r2.json() == []


def test_summary_on_agent_with_no_turns(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        r = c.get(f"/api/agents/{agent['id']}/summary")
        assert r.status_code == 200
        assert r.json()["turns"]["total"] == 0


# ------------------------------------------------------------------ 5.4 (re)evaluation
def test_evaluate_single_turn_creates_new_attempt(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        turn_id = c.get(f"/api/agents/{agent['id']}/turns").json()[0]["id"]
        # ingest already queued attempt 1 automatically (turn.end -> maybe_queue_evaluation)
        r = c.post(f"/api/agents/{agent['id']}/turns/{turn_id}/evaluate", json={"evaluators": ["judge:1"]})
        assert r.status_code == 202
        assert r.json()["attempt_no"] == 2
        r2 = c.post(f"/api/agents/{agent['id']}/turns/{turn_id}/evaluate", json={"evaluators": ["judge:2"]})
        assert r2.json()["attempt_no"] == 3


def test_bulk_reevaluate(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        _ingest(c, agent["token"], _turn_events("t2"))
        r = c.post(f"/api/agents/{agent['id']}/reevaluate", json={})
        assert r.status_code == 202
        assert r.json()["queued"] == 2


# ------------------------------------------------------------------ 5.6 export
def test_export_csv_and_json(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        r = c.get(f"/api/agents/{agent['id']}/export?format=csv")
        assert r.status_code == 200 and "turn_id" in r.text
        r = c.get(f"/api/agents/{agent['id']}/export?format=json")
        assert r.status_code == 200 and r.json()["turns"][0]["external_id"] == "t1"


# ------------------------------------------------------------------ 5.5 SSE
# Note: the agent events stream never terminates on its own (there is no "run_finished"-style terminal event for
# a live agent feed - see EventHub.subscribe_open), and Starlette's TestClient drives a streamed request to
# completion synchronously, so it cannot exercise a genuinely open-ended stream end-to-end without hanging.
# `tests/test_event_hub.py` covers `subscribe_open` directly; here we only check that ingest publishes to the
# right channel, which is what the endpoint then streams.
def test_ingest_publishes_the_turn_lifecycle_to_the_agent_channel(settings, file_session_factory):
    from app.core.events import agent_channel

    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        _ingest(c, agent["token"], _turn_events("t1"))
        buffered = c.app.state.hub._streams[agent_channel(agent["id"])].events
        assert [e.type for e in buffered] == ["turn_started", "span_added", "turn_finished"]
