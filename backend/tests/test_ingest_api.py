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
            declared_models={"default": "qwen3:8b"},
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
            "event_id": "e3",
            "session_id": "s1",
            "turn_id": turn_id,
            "type": "turn.end",
            "status": "ok",
            "output": "hello",
            # add-otel-tracing: turn.end reports these directly - no `span` event to derive them from
            "models": ["qwen3:8b"],
            "prompt_tokens": 20,
            "completion_tokens": 5,
        },
    ]


def test_batch_accepted_and_stored(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"accepted": 2, "duplicates": 0, "rejected": []}
    with file_session_factory() as session:
        turns = repo.list_turns(session, agent_id)
        assert len(turns) == 1
        assert turns[0].status == "ok"
        assert turns[0].models == ["qwen3:8b"]
        assert repo.get_agent(session, agent_id).last_seen_at is not None


def test_turn_start_system_prompt_is_stored_and_returned(settings, file_session_factory):
    """add-agent-playground: the system prompt actually in effect for a turn (post skill-composition),
    reported directly by `turn.start`, round-trips through storage and the turn API."""
    agent_id, token = _make_agent(file_session_factory)
    events = [
        {
            "v": 1, "event_id": "e1", "session_id": "s1", "turn_id": "t1", "type": "turn.start",
            "input": "2+2?", "system_prompt": "Step A instructions\n\nbe terse",
        },
        {
            "v": 1, "event_id": "e2", "session_id": "s1", "turn_id": "t1", "type": "turn.end",
            "status": "ok", "output": "4", "models": ["qwen3:8b"],
        },
    ]
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        turns = c.get(f"/api/agents/{agent_id}/turns").json()
        assert turns[0]["system_prompt"] == "Step A instructions\n\nbe terse"


def test_turn_start_without_system_prompt_leaves_it_absent(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        turns = c.get(f"/api/agents/{agent_id}/turns").json()
        assert turns[0]["system_prompt"] is None


def test_span_event_in_a_batch_is_rejected_individually_turn_start_and_end_still_accepted(
    settings, file_session_factory
):
    """add-otel-tracing 5.1: the retired `span` event type is now just unrecognized - only it is
    rejected, not the whole batch."""
    agent_id, token = _make_agent(file_session_factory)
    events = _events()
    span = {
        "v": 1,
        "event_id": "e2",
        "session_id": "s1",
        "turn_id": "t1",
        "type": "span",
        "span_id": "sp1",
        "kind": "llm",
        "model": "qwen3:8b",
        "output": "hello",
    }
    batch = [events[0], span, events[1]]
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=batch, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accepted"] == 2
        assert body["rejected"] == [{"index": 1, "reason": body["rejected"][0]["reason"]}]
        assert "span" in body["rejected"][0]["reason"]
    with file_session_factory() as session:
        turn = repo.list_turns(session, agent_id)[0]
        assert turn.status == "ok" and turn.output == "hello"


def test_turn_end_in_a_later_request_than_turn_start(settings, file_session_factory):
    """Regression: a real agent (and the reference SDK) sends `turn.start` the instant a turn begins and
    `turn.end` only once its LLM call returns - two *separate* requests, not one batch like `_events()` above.
    `turn.started_at` is then read back fresh from the database in the second request; subtracting it from the
    freshly-parsed `ended_at` must not raise (naive vs. aware datetimes), or the whole `turn.end` request 500s
    and the turn is stuck `open` until the abandonment sweep - exactly the reported "output is never fed" bug."""
    events = _events()
    agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=[events[0]], headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        r = c.post("/api/ingest/v1/events", json=events[1:], headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text  # must not 500
        assert r.json() == {"accepted": 1, "duplicates": 0, "rejected": []}
    with file_session_factory() as session:
        turn = repo.list_turns(session, agent_id)[0]
        assert turn.status == "ok"
        assert turn.output == "hello"
        assert turn.latency_ms is not None


def test_retried_batch_is_all_duplicates(settings, file_session_factory):
    _, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        r = c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
        assert r.json() == {"accepted": 0, "duplicates": 2, "rejected": []}


def test_partial_batch_rejection_reports_index(settings, file_session_factory):
    _, token = _make_agent(file_session_factory)
    events = _events()
    bad = dict(events[1])
    bad["status"] = "not-a-valid-status"  # only "ok"/"error" are accepted
    bad["event_id"] = "e-bad"  # a distinct id, or this "duplicate" of a rejected event is itself ambiguous
    batch = [events[0], bad]
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/ingest/v1/events", json=batch, headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        assert body["accepted"] == 1
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


# ------------------------------------------------------------------ add-agent-self-discovery: GET /v1/whoami
def test_whoami_returns_name_kind_declared_models_and_computed_gateway_groups(settings, file_session_factory):
    with file_session_factory() as session:
        agent, token = repo.create_agent(
            session,
            name="My Reasoner!",
            kind="reasoning",
            declared_models={"reasoning": "qwen3:8b", "generation": "gemma4:e4b"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "My Reasoner!"
        assert body["kind"] == "reasoning"
        assert body["declared_models"] == {"reasoning": "qwen3:8b", "generation": "gemma4:e4b"}
        # "My Reasoner!" -> "my-reasoner" (agent_slug in gateway_sync.py) - same computation the real sync uses
        assert body["gateway_model_groups"] == {
            "reasoning": "my-reasoner__reasoning",
            "generation": "my-reasoner__generation",
        }


def test_whoami_matches_the_group_names_a_real_sync_would_use(settings, file_session_factory):
    """The exact same functions (`agent_slug`/`model_group_name`) back both the sync step and this endpoint -
    this test pins that by calling them directly and comparing, so the two can never silently drift apart."""
    from app.core.gateway_sync import agent_slug, model_group_name

    with file_session_factory() as session:
        agent, token = repo.create_agent(
            session,
            name="demo-reasoner",
            kind="reasoning",
            declared_models={"reasoning": "qwen3:8b"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        body = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
        expected = model_group_name(agent_slug(agent.name), "reasoning")
        assert body["gateway_model_groups"]["reasoning"] == expected


def test_whoami_unauthorized_without_valid_token(settings, file_session_factory):
    _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/whoami", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        r = c.get("/api/ingest/v1/whoami")
        assert r.status_code == 401


def test_whoami_succeeds_even_when_the_agent_is_paused(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with file_session_factory() as session:
        repo.set_agent_status(session, agent_id, "paused")
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["name"] == "bot"


# ------------------------------------------------------------------ add-custom-model-provider-kind
def test_whoami_exposes_a_custom_providers_endpoint_instead_of_a_gateway_group(settings, file_session_factory):
    with file_session_factory() as session:
        repo.create_provider(
            session,
            kind="custom",
            name="context-classifier",
            key_env=None,
            base_url="http://127.0.0.1:8765",
            ack_at=None,
        )
        agent, token = repo.create_agent(
            session,
            name="classifier-router",
            kind="reasoning",
            declared_models={"routing": "qwen3:8b", "classification": "@context-classifier/classify"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        body = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
    # the gateway-routed task is unaffected
    assert body["gateway_model_groups"] == {"routing": "classifier-router__routing"}
    # the custom-kind task has no gateway group at all - its connection info instead
    assert "classification" not in body["gateway_model_groups"]
    assert body["custom_model_endpoints"] == {
        "classification": {"base_url": "http://127.0.0.1:8765", "model_id": "classify"}
    }


def test_whoami_custom_model_endpoints_is_empty_when_nothing_is_custom(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        body = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["custom_model_endpoints"] == {}


def test_whoami_custom_endpoint_carries_no_secret_even_with_an_adversarial_name(settings, file_session_factory):
    """A custom provider's base URL is returned as-is (it's an address, not a credential) - but nothing beyond
    `base_url`/`model_id` must ever appear for it, even if an operator names things to look secret-like."""
    with file_session_factory() as session:
        repo.create_provider(
            session,
            kind="custom",
            name="looks-like-a-token-abc123",
            key_env=None,
            base_url="http://127.0.0.1:9999/sk-not-a-real-secret",
            ack_at=None,
        )
        agent, token = repo.create_agent(
            session,
            name="bot2",
            kind="reasoning",
            declared_models={"classification": "@looks-like-a-token-abc123/model-id"},
            eval_config=EvalConfigIn(),
            rubric=None,
        )
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        body = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
    endpoint = body["custom_model_endpoints"]["classification"]
    assert set(endpoint) == {"base_url", "model_id"}
    assert endpoint == {"base_url": "http://127.0.0.1:9999/sk-not-a-real-secret", "model_id": "model-id"}
    for forbidden in ("token", "token_hash", "token_prefix", "api_key", "gateway"):
        assert forbidden not in body


def test_whoami_never_returns_a_secret(settings, file_session_factory):
    _agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        body = c.get("/api/ingest/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
        assert set(body) == {
            "name",
            "kind",
            "declared_models",
            "gateway_model_groups",
            "custom_model_endpoints",
        }
        serialized = str(body)
        assert token not in serialized
        for forbidden in ("token", "token_hash", "token_prefix", "api_key", "gateway"):
            assert forbidden not in body


# ------------------------------------------------------------------ add-agent-playground: GET /v1/skills/{name}
def test_skill_fetch_returns_name_description_instructions(settings, file_session_factory):
    from app.schemas import SkillIn

    _agent_id, token = _make_agent(file_session_factory)
    with file_session_factory() as session:
        repo.create_skill(session, SkillIn(name="step-by-step", description="desc", instructions="Think step by step."))
        session.commit()
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/skills/step-by-step", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"name": "step-by-step", "description": "desc", "instructions": "Think step by step."}


def test_skill_fetch_unknown_name_is_404(settings, file_session_factory):
    _agent_id, token = _make_agent(file_session_factory)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/skills/does-not-exist", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404


def test_skill_fetch_unauthorized_without_valid_token(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/ingest/v1/skills/anything", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401


def test_unsampled_turn_is_not_queued_for_evaluation(settings, file_session_factory):
    agent_id, token = _make_agent(file_session_factory, evaluators=["gemma3:4b"], sample_rate=0.0)
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        c.post("/api/ingest/v1/events", json=_events(), headers={"Authorization": f"Bearer {token}"})
    with file_session_factory() as session:
        turn = repo.list_turns(session, agent_id)[0]
        assert repo.get_evaluation.__module__  # sanity that repo import works
        from app.models import TurnEvaluation

        assert session.query(TurnEvaluation).filter(TurnEvaluation.turn_id == turn.id).count() == 0
