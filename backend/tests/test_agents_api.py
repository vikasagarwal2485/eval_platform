import dataclasses

from tests.fakes import FakeOllama
from tests.helpers import new_client
from tests.test_gateway_sync import GATEWAY_URL, _MockGateway, _patch_gateway


def _create_agent(c, **over):
    body = {"name": "bot", "kind": "chatbot", "declared_models": {"default": "author:1"}, **over}
    r = c.post("/api/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ingest(c, token, events):
    return c.post("/api/ingest/v1/events", json=events, headers={"Authorization": f"Bearer {token}"})


def _turn_events(ext="t1", author="author:1"):
    return [
        {"v": 1, "event_id": f"{ext}s", "session_id": "s1", "turn_id": ext, "type": "turn.start", "input": "hi"},
        {
            "v": 1,
            "event_id": f"{ext}e",
            "session_id": "s1",
            "turn_id": ext,
            "type": "turn.end",
            "status": "ok",
            "output": "hello",
            "models": [author],  # add-otel-tracing: turn.end reports this directly, no `span` event
        },
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


def test_router_kind_is_accepted(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        created = _create_agent(c, name="router-bot", kind="router", handoff_agent_names=["reasoner"])
        assert created["kind"] == "router"


def test_invalid_kind_is_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={"name": "bot", "kind": "orchestrator", "declared_models": {"default": "x:1"}},
        )
        assert r.status_code == 422


def test_duplicate_name_is_409(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c)
        r = c.post("/api/agents", json={"name": "bot", "kind": "chatbot", "declared_models": {"default": "x:1"}})
        assert r.status_code == 409


def test_self_evaluator_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": "author:1"},
                "eval_config": {"evaluators": ["author:1"]},
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_settings"


def test_self_evaluator_rejected_when_it_matches_any_declared_model(settings, file_session_factory):
    """spec agent-registry, 'A multi-model agent is checked against all of its declared models, not just one' -
    an evaluator matching the *second* declared model is rejected exactly like matching the first."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "reasoning",
                "declared_models": {"reasoning": "author:1", "generation": "author:2"},
                "eval_config": {"evaluators": ["author:2"]},  # matches only the second entry
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_settings"


def test_evaluator_distinct_from_every_declared_model_is_accepted(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "reasoning",
                "declared_models": {"reasoning": "author:1", "generation": "author:2"},
                "eval_config": {"evaluators": ["judge:1"]},
            },
        )
        assert r.status_code == 201


def test_empty_declared_models_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/agents", json={"name": "bot", "kind": "chatbot", "declared_models": {}})
        assert r.status_code == 422


def test_malformed_declared_model_reference_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={"name": "bot", "kind": "chatbot", "declared_models": {"default": "@bad-provider-name!/x"}},
        )
        assert r.status_code == 422
        assert "declared_models['default']" in r.text


# ------------------------------------------------------------------ add-gateway-model-sync: declared model
# objects (generation-parameter overrides alongside the model reference)
def test_declared_model_as_object_with_params_is_accepted(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(
            c,
            declared_models={
                "reasoning": {"model": "author:1", "params": {"temperature": 0.2}},
                "generation": "author:2",
            },
        )
        assert agent["declared_models"]["reasoning"] == {"model": "author:1", "params": {"temperature": 0.2}}
        assert agent["declared_models"]["generation"] == "author:2"  # plain string untouched


def test_plain_string_declared_model_still_works_unchanged(settings, file_session_factory):
    """task 2.1 regression check: nothing about the existing plain-string path changes."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, declared_models={"default": "author:1"})
        assert agent["declared_models"] == {"default": "author:1"}


# ------------------------------------------------------------------ add-declared-model-fallback
def test_declared_model_with_fallback_is_accepted_and_round_trips(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(
            c, declared_models={"default": {"model": "author:1", "fallback": "author:2"}}
        )
        assert agent["declared_models"]["default"] == {"model": "author:1", "fallback": "author:2"}


def test_declared_model_without_fallback_still_omits_the_field(settings, file_session_factory):
    """task 1.1 regression check: a plain-string entry, and an object entry with no fallback set, are both
    unaffected by the new field - `fallback` is never serialized as a bare `null`."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(
            c, declared_models={"default": {"model": "author:1", "params": {"temperature": 0.2}}}
        )
        assert agent["declared_models"]["default"] == {"model": "author:1", "params": {"temperature": 0.2}}
        assert "fallback" not in agent["declared_models"]["default"]


def test_malformed_declared_model_fallback_reference_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "author:1", "fallback": "@bad-provider-name!/x"}},
            },
        )
        assert r.status_code == 422
        assert "declared_models['default'].fallback" in r.text


def test_hosted_declared_model_fallback_requires_ack(settings, file_session_factory):
    """A declared model's fallback sends this agent's live traffic to that provider just as the primary model
    does, whenever the primary fails - it needs the same data-sharing acknowledgment."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "author:1", "fallback": "@openai-main/gpt-4o"}},
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        assert r.json()["detail"]["provider"] == "openai-main"
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "author:1", "fallback": "@openai-main/gpt-4o"}},
                "provider_acks": ["openai-main"],
            },
        )
        assert r.status_code == 201


def test_hosted_declared_model_fallback_requires_ack_on_update_too(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        r = c.patch(
            f"/api/agents/{agent['id']}",
            json={"declared_models": {"default": {"model": "author:1", "fallback": "@openai-main/gpt-4o"}}},
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        r = c.patch(
            f"/api/agents/{agent['id']}",
            json={
                "declared_models": {"default": {"model": "author:1", "fallback": "@openai-main/gpt-4o"}},
                "provider_acks": ["openai-main"],
            },
        )
        assert r.status_code == 200


def test_declared_model_object_with_non_dict_params_rejected(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "author:1", "params": "not-an-object"}},
            },
        )
        assert r.status_code == 422
        assert "declared_models" in r.text and "default" in r.text  # names the offending key


def test_self_evaluator_rejected_when_declared_as_an_object(settings, file_session_factory):
    """the self-evaluator check reads the model out of either shape (declared_model_ref)."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "author:1", "params": {"temperature": 0.2}}},
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
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": "author:1"},
                "eval_config": {"evaluators": ["@openai-main/gpt-4o"]},
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": "author:1"},
                "eval_config": {"evaluators": ["@openai-main/gpt-4o"]},
                "provider_acks": ["openai-main"],
            },
        )
        assert r.status_code == 201


def test_hosted_declared_model_requires_ack(settings, file_session_factory):
    """An agent's own declared model sends every live turn to that provider - at least as much exposure as an
    evaluator, so it needs the same data-sharing acknowledgment."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={"name": "bot", "kind": "chatbot", "declared_models": {"default": "@openai-main/gpt-4o"}},
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        assert r.json()["detail"]["provider"] == "openai-main"
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": "@openai-main/gpt-4o"},
                "provider_acks": ["openai-main"],
            },
        )
        assert r.status_code == 201


def test_hosted_declared_model_requires_ack_on_update_too(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        r = c.patch(f"/api/agents/{agent['id']}", json={"declared_models": {"default": "@openai-main/gpt-4o"}})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"
        r = c.patch(
            f"/api/agents/{agent['id']}",
            json={"declared_models": {"default": "@openai-main/gpt-4o"}, "provider_acks": ["openai-main"]},
        )
        assert r.status_code == 200
        assert r.json()["declared_models"] == {"default": "@openai-main/gpt-4o"}


def test_hosted_declared_model_as_an_object_still_requires_ack(settings, file_session_factory):
    """The acknowledgment check reads the model ref out of either declared_models shape - a plain string or a
    {"model": ..., "params": ...} object (add-gateway-model-sync)."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "bot",
                "kind": "chatbot",
                "declared_models": {"default": {"model": "@openai-main/gpt-4o", "params": {"temperature": 0.2}}},
            },
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ack_required"


def test_declared_models_round_trips_through_create_read_update(settings, file_session_factory):
    """task 4.1: a multi-entry declared_models map survives create -> read -> update unchanged in shape."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, declared_models={"reasoning": "author:1", "generation": "author:2"})
        assert agent["declared_models"] == {"reasoning": "author:1", "generation": "author:2"}
        got = c.get(f"/api/agents/{agent['id']}").json()
        assert got["declared_models"] == {"reasoning": "author:1", "generation": "author:2"}
        r = c.patch(f"/api/agents/{agent['id']}", json={"declared_models": {"reasoning": "author:3"}})
        assert r.status_code == 200
        assert r.json()["declared_models"] == {"reasoning": "author:3"}


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
        assert detail["models"] == ["author:1"]  # add-otel-tracing: reported by turn.end, no spans list anymore
        assert detail["spans"] == []
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
        # add-otel-tracing: no more "span_added" event - the `span` event type is retired
        assert [e.type for e in buffered] == ["turn_started", "turn_finished"]


# ------------------------------------------------------------------ add-gateway-model-sync (4.2-4.4)
def test_registration_succeeds_even_when_the_gateway_is_unreachable(settings, file_session_factory, monkeypatch):
    """task 4.2: a gateway sync failure never blocks saving the agent."""
    _patch_gateway(monkeypatch, _MockGateway(fail=True))
    gw_settings = dataclasses.replace(settings, gateway_url=GATEWAY_URL)
    with new_client(gw_settings, file_session_factory, FakeOllama()) as c:
        r = c.post("/api/agents", json={"name": "bot", "kind": "reasoning", "declared_models": {"default": "x:1"}})
        assert r.status_code == 201
        assert r.json()["gateway_sync"]["default"]["status"] == "error"


def test_registration_behaves_identically_for_an_agent_that_never_uses_the_gateway(
    settings, file_session_factory, monkeypatch
):
    """task 4.3: gateway sync is attempted regardless of kind, but its outcome affects nothing besides the
    `gateway_sync` field - a chatbot-style agent registers and works the same whether the gateway is up or down."""
    for i, gw in enumerate((_MockGateway(), _MockGateway(fail=True))):
        _patch_gateway(monkeypatch, gw)
        gw_settings = dataclasses.replace(settings, gateway_url=GATEWAY_URL)
        with new_client(gw_settings, file_session_factory, FakeOllama()) as c:
            agent = _create_agent(c, name=f"chatbot-{i}", kind="chatbot")
            r = c.get(f"/api/agents/{agent['id']}")
            assert r.status_code == 200
            assert r.json()["declared_models"] == {"default": "author:1"}


def test_updating_declared_models_removes_the_gateway_group_for_a_dropped_task_type(
    settings, file_session_factory, monkeypatch
):
    """task 4.4."""
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    gw_settings = dataclasses.replace(settings, gateway_url=GATEWAY_URL)
    with new_client(gw_settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(
            c,
            name="two-task-agent",
            kind="reasoning",
            declared_models={"reasoning": "author:1", "generation": "author:2"},
        )
        assert {m["model_name"] for m in gw.db_models.values()} == {
            "two-task-agent__reasoning",
            "two-task-agent__generation",
        }
        r = c.patch(f"/api/agents/{agent['id']}", json={"declared_models": {"reasoning": "author:1"}})
        assert r.status_code == 200
        assert r.json()["gateway_sync"]["generation"]["status"] == "ok"
        assert {m["model_name"] for m in gw.db_models.values()} == {"two-task-agent__reasoning"}


def test_updating_an_unrelated_setting_does_not_touch_the_gateway(settings, file_session_factory, monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    gw_settings = dataclasses.replace(settings, gateway_url=GATEWAY_URL)
    with new_client(gw_settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        gw.calls.clear()
        r = c.patch(f"/api/agents/{agent['id']}", json={"eval_config": {"evaluators": ["judge:1"]}})
        assert r.status_code == 200
        assert "gateway_sync" not in r.json()
        assert gw.calls == []  # no gateway request at all for a settings change that isn't declared_models


# ------------------------------------------------------------------ add-agent-playground: enable/disable/rotate
def _pg_settings(settings, **over):
    return dataclasses.replace(settings, gateway_url=GATEWAY_URL, playground_secret_key="a-test-passphrase", **over)


def test_enable_playground_requires_matching_flavor_kind(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "reasoning"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "flavor_kind_mismatch"


def test_enable_playground_rejects_an_unknown_flavor(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "nope"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "unknown_flavor"


def test_enable_playground_requires_eval_secret_key_configured(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    gw_settings = dataclasses.replace(settings, gateway_url=GATEWAY_URL)  # no playground_secret_key
    with new_client(gw_settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "playground_secrets_disabled"


def test_enable_playground_succeeds_and_mints_a_scoped_gateway_key(settings, file_session_factory, monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        assert r.status_code == 200
        body = r.json()
        assert "token" in body and body["token"]  # shown once, like registration
        assert body["playground_eligible"] is True
        assert body["flavor"] == "chatbot"
        assert body["playground_gateway_key_configured"] is True
        assert body["gateway_key_mint"]["status"] == "ok"
        # the new ingest token actually authenticates - the old registration token was rotated away
        r2 = c.get(f"/api/agents/{agent['id']}")
        assert r2.json()["playground_gateway_key_configured"] is True
        assert "token" not in r2.json()
        assert any(call[1] == "/key/generate" for call in gw.calls)


def test_enable_playground_never_returns_the_gateway_key_itself(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        body = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"}).json()
        assert "playground_gateway_key_enc" not in body
        assert "playground_ingest_token_enc" not in body


def test_enable_playground_reports_a_mint_failure_without_blocking(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway(fail=True))
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        assert r.status_code == 200  # still succeeds
        assert r.json()["gateway_key_mint"]["status"] == "error"
        assert r.json()["playground_gateway_key_configured"] is False


def test_disable_playground_clears_eligibility_but_keeps_the_registration(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        r = c.post(f"/api/agents/{agent['id']}/playground/disable")
        assert r.status_code == 200
        body = r.json()
        assert body["playground_eligible"] is False
        assert body["flavor"] is None
        assert body["playground_gateway_key_configured"] is False
        assert body["name"] == "bot"  # registration itself untouched


def test_rotate_playground_credentials_requires_eligibility(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/rotate")
        assert r.status_code == 409


def test_rotate_playground_credentials_reissues_token_and_remints_key(settings, file_session_factory, monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        first = c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"}).json()
        r = c.post(f"/api/agents/{agent['id']}/playground/rotate")
        assert r.status_code == 200
        second = r.json()
        assert second["token"] != first["token"]
        # the old (enable-issued) token no longer authenticates ingest
        ir = c.post(
            "/api/ingest/v1/events", json=[], headers={"Authorization": f"Bearer {first['token']}"}
        )
        assert ir.status_code == 401


def test_updating_declared_models_remints_the_stored_gateway_key(settings, file_session_factory, monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="reasoning", declared_models={"reasoning": "author:1"})
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "reasoning"})
        gw.calls.clear()
        r = c.patch(
            f"/api/agents/{agent['id']}",
            json={"declared_models": {"reasoning": "author:1", "generation": "author:2"}},
        )
        assert r.status_code == 200
        assert r.json()["gateway_key_mint"]["status"] == "ok"
        mint_calls = [call for call in gw.calls if call[1] == "/key/generate"]
        assert len(mint_calls) == 1
        assert set(mint_calls[0][2]["models"]) == {"bot__reasoning", "bot__generation"}


def test_updating_an_unrelated_setting_does_not_remint_the_gateway_key(settings, file_session_factory, monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        gw.calls.clear()
        r = c.patch(f"/api/agents/{agent['id']}", json={"eval_config": {"evaluators": ["judge:1"]}})
        assert r.status_code == 200
        assert "gateway_key_mint" not in r.json()
        assert not any(call[1] == "/key/generate" for call in gw.calls)


# ------------------------------------------------------------------ add-agent-playground: handoff_agent_names
def test_handoff_agent_names_requires_router_kind(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        r = c.post(
            "/api/agents",
            json={
                "name": "bot", "kind": "chatbot", "declared_models": {"default": "author:1"},
                "handoff_agent_names": ["reasoner"],
            },
        )
        assert r.status_code == 422


def test_handoff_agent_names_mandatory_for_router_kind_at_registration(settings, file_session_factory):
    """Point 1: a router-kind agent with zero hand-off agents configured could never hand anything
    off - enforced at registration, not just on later settings saves."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={"name": "router", "kind": "router", "declared_models": {"routing": "author:1"}},
        )
        assert r.status_code == 422
        assert "at least one" in r.json()["detail"]["message"]


def test_handoff_agent_names_must_name_an_existing_reasoning_agent(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "router", "kind": "router", "declared_models": {"routing": "author:1"},
                "handoff_agent_names": ["no-such-agent"],
            },
        )
        assert r.status_code == 422


def test_handoff_agent_names_accepts_a_target_of_any_kind(settings, file_session_factory):
    """A hand-off target's own registered kind is purely descriptive - nothing in the spawn
    mechanism depends on it (`app.core.playground_spawn`'s router branch only ever checks the
    target is playground-eligible, never its kind), so it is unconstrained: chatbot, reasoning or
    router are all accepted."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="chatbot-target", kind="chatbot")
        agent = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["chatbot-target"],
        )
        assert agent["handoff_agent_names"] == ["chatbot-target"]


def test_handoff_agent_names_rejects_self_reference(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.post(
            "/api/agents",
            json={
                "name": "router", "kind": "router", "declared_models": {"routing": "author:1"},
                "handoff_agent_names": ["router"],
            },
        )
        assert r.status_code == 422


def test_handoff_agent_names_rejects_duplicates(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        r = c.post(
            "/api/agents",
            json={
                "name": "router", "kind": "router", "declared_models": {"routing": "author:1"},
                "handoff_agent_names": ["reasoner", "reasoner"],
            },
        )
        assert r.status_code == 422


def test_handoff_agent_names_accepted_for_a_valid_router_and_target(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        agent = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner"],
        )
        assert agent["handoff_agent_names"] == ["reasoner"]


def test_handoff_agent_names_accepts_more_than_one(settings, file_session_factory):
    """Point 2: the registry places no limit on how many hand-off agents a router declares, even
    though today's one reference router script only ever consumes the first."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner-a", kind="reasoning")
        _create_agent(c, name="reasoner-b", kind="reasoning")
        agent = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner-a", "reasoner-b"],
        )
        assert agent["handoff_agent_names"] == ["reasoner-a", "reasoner-b"]


def test_handoff_agent_names_empty_by_default_for_non_router_kinds(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c)
        assert agent["handoff_agent_names"] == []


def test_handoff_agent_names_survives_an_unrelated_settings_save(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        router = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner"],
        )
        r = c.patch(f"/api/agents/{router['id']}", json={"eval_config": {"evaluators": ["judge:1"]}})
        assert r.status_code == 200
        assert r.json()["handoff_agent_names"] == ["reasoner"]


def test_handoff_agent_names_can_be_set_to_an_empty_list_explicitly(settings, file_session_factory):
    """`[]` unambiguously clears it - no separate clear_* flag needed, unlike the single-name field
    this replaced."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        router = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner"],
        )
        # emptying it while staying router-kind is itself rejected (router must have >= 1)...
        r = c.patch(f"/api/agents/{router['id']}", json={"handoff_agent_names": []})
        assert r.status_code == 422
        # ...but succeeds together with a kind change away from router in the same request
        r2 = c.patch(f"/api/agents/{router['id']}", json={"kind": "chatbot", "handoff_agent_names": []})
        assert r2.status_code == 200
        assert r2.json()["handoff_agent_names"] == []


# ------------------------------------------------------------------ add-agent-playground: spawn endpoint
def test_spawn_rejects_a_non_eligible_agent(settings, file_session_factory, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.post(f"/api/agents/{agent['id']}/playground/spawn", json={"task": "hi"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "spawn_failed"


def test_spawn_launches_the_subprocess_with_the_expected_argv(settings, file_session_factory, monkeypatch, tmp_path):
    from app.core import agent_catalog, playground_spawn

    _patch_gateway(monkeypatch, _MockGateway())
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    monkeypatch.setattr(agent_catalog, "flavor_root", lambda flavor: tmp_path)

    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["argv"] = args

        class _Proc:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return _Proc()

    monkeypatch.setattr(playground_spawn.asyncio, "create_subprocess_exec", fake_exec)

    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        r = c.post(
            f"/api/agents/{agent['id']}/playground/spawn",
            json={"system_prompt": "be terse", "skills": ["step-by-step"], "task": "2+2?"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        argv = list(captured["argv"])
        assert str(venv_python) in argv
        assert "--platform-url" in argv
        assert "--model" in argv and argv[argv.index("--model") + 1] == "author:1"
        assert "--system-prompt" in argv and argv[argv.index("--system-prompt") + 1] == "be terse"
        assert "--skill" in argv and argv[argv.index("--skill") + 1] == "step-by-step"
        assert argv[-2:] == ["--task", "2+2?"]


# ------------------------------------------------------------------ editing an agent's kind
def test_kind_can_be_edited_via_settings_update(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.patch(f"/api/agents/{agent['id']}", json={"declared_models": agent["declared_models"], "kind": "reasoning"})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "reasoning"
        assert c.get(f"/api/agents/{agent['id']}").json()["kind"] == "reasoning"


def test_omitting_kind_leaves_it_unchanged(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        r = c.patch(f"/api/agents/{agent['id']}", json={"eval_config": {"evaluators": ["judge:1"]}})
        assert r.status_code == 200
        assert r.json()["kind"] == "chatbot"


def test_kind_change_rejected_when_playground_eligible_flavor_mismatches(
    settings, file_session_factory, monkeypatch
):
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        r = c.patch(f"/api/agents/{agent['id']}", json={"kind": "reasoning"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_settings"
        assert "playground-eligible" in r.json()["detail"]["message"]
        # unchanged
        assert c.get(f"/api/agents/{agent['id']}").json()["kind"] == "chatbot"


def test_kind_change_allowed_when_playground_flavor_still_matches(settings, file_session_factory, monkeypatch):
    """Changing to a different setting that happens to equal the already-matching kind is a no-op
    for this check - verifies the check is about the *flavor*, not a blanket freeze."""
    _patch_gateway(monkeypatch, _MockGateway())
    with new_client(_pg_settings(settings), file_session_factory, FakeOllama()) as c:
        agent = _create_agent(c, kind="chatbot")
        c.post(f"/api/agents/{agent['id']}/playground/enable", json={"flavor": "chatbot"})
        r = c.patch(f"/api/agents/{agent['id']}", json={"kind": "chatbot"})
        assert r.status_code == 200


def test_kind_change_allowed_for_an_agent_that_is_a_routers_handoff_target(settings, file_session_factory):
    """A hand-off target's kind is unconstrained (see `test_handoff_agent_names_accepts_a_target_of_
    any_kind`), so changing it away from 'reasoning' no longer needs to check whether any router
    depends on it still being one - that dependency doesn't exist anymore."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner"],
        )
        target = c.get("/api/agents").json()
        target_id = next(a["id"] for a in target if a["name"] == "reasoner")
        r = c.patch(f"/api/agents/{target_id}", json={"kind": "chatbot"})
        assert r.status_code == 200
        assert r.json()["kind"] == "chatbot"
        # the router's own handoff_agent_names is untouched by its target's kind changing
        router_id = next(a["id"] for a in target if a["name"] == "router")
        assert c.get(f"/api/agents/{router_id}").json()["handoff_agent_names"] == ["reasoner"]


def test_kind_change_to_router_rejected_unless_handoff_targets_are_cleared_or_valid(
    settings, file_session_factory
):
    """A router-kind agent that already has handoff_agent_names set keeps it across an unrelated
    settings save (existing value carried over) - so changing kind *away* from router while it's
    still set is rejected by the existing handoff validator, consistent with changing kind and
    handoff_agent_names together being the correct way to do it."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="reasoner", kind="reasoning")
        router = _create_agent(
            c, name="router", kind="router", declared_models={"routing": "author:1"},
            handoff_agent_names=["reasoner"],
        )
        r = c.patch(f"/api/agents/{router['id']}", json={"kind": "chatbot"})
        assert r.status_code == 422
        assert "handoff_agent_names" in r.json()["detail"]["message"]

        # clearing handoff_agent_names (to []) in the same request allows the kind change
        r2 = c.patch(f"/api/agents/{router['id']}", json={"kind": "chatbot", "handoff_agent_names": []})
        assert r2.status_code == 200
        assert r2.json()["kind"] == "chatbot"
        assert r2.json()["handoff_agent_names"] == []
