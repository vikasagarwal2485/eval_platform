"""`add-gateway-model-sync` tasks 3.1-3.4: the registry-to-gateway sync mechanism, against a mocked gateway (no
live process needed - `tests/test_live_smoke_gateway.py` covers the real thing, opt-in)."""

from __future__ import annotations

import json

import httpx
import pytest

from app import repo
from app.config import Settings
from app.core.gateway_sync import (
    agent_gateway_group_names,
    fallback_group_name,
    mint_virtual_key,
    model_group_name,
    sync_agent_model_groups,
    to_litellm_params,
)
from app.models import Agent

GATEWAY_URL = "http://gateway.local"


def _settings(**over) -> Settings:
    return Settings(gateway_url=GATEWAY_URL, ollama_base_url="http://ollama.local", **over)


def _agent(session, declared_models: dict) -> Agent:
    a = Agent(
        name="my-reasoner",
        kind="reasoning",
        declared_models=declared_models,
        status="active",
        token_hash="h",
        token_prefix="p",
        eval_config={},
        provider_acks={},
    )
    session.add(a)
    session.flush()
    return a


class _MockGateway:
    """A minimal in-memory stand-in for the gateway's `/model/info`, `/model/new`, `/model/update`,
    `/model/delete` and `/key/generate`, recording every call for assertions."""

    def __init__(self, *, static_groups: list[str] | None = None, fail: bool = False):
        self.db_models: dict[str, dict] = {}  # model_id -> {"model_name", "litellm_params"}
        self.static_groups = set(static_groups or [])
        self.fail = fail
        self.calls: list[tuple[str, str, dict | None]] = []
        self._next_id = 1
        self._next_key_id = 1
        self.minted_aliases: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))

        if path == "/model/info" and request.method == "GET":
            data = [
                {"model_name": n, "model_info": {"id": f"static-{n}", "db_model": False}} for n in self.static_groups
            ] + [
                {"model_name": m["model_name"], "model_info": {"id": mid, "db_model": True}}
                for mid, m in self.db_models.items()
            ]
            return httpx.Response(200, json={"data": data})
        if path == "/model/new" and request.method == "POST":
            model_id = f"id-{self._next_id}"
            self._next_id += 1
            self.db_models[model_id] = {"model_name": body["model_name"], "litellm_params": body["litellm_params"]}
            return httpx.Response(200, json={"model_id": model_id})
        if path == "/model/update" and request.method == "POST":
            model_id = body["model_info"]["id"]
            self.db_models[model_id] = {"model_name": body["model_name"], "litellm_params": body["litellm_params"]}
            return httpx.Response(200, json={"model_id": model_id})
        if path == "/model/delete" and request.method == "POST":
            self.db_models.pop(body["id"], None)
            return httpx.Response(200, json={"message": "deleted"})
        if path == "/key/generate" and request.method == "POST":
            alias = body.get("key_alias")
            if alias is not None and alias in self.minted_aliases:
                # Mirrors litellm's own real behavior: a `key_alias` already in use is rejected -
                # this mock only accepts a second `/key/generate` for the same alias once it's been
                # cleared by `/key/delete` first (`gateway_sync.mint_virtual_key`'s pre-delete fix).
                return httpx.Response(
                    400, json={"error": f"Key with alias '{alias}' already exists."}
                )
            key = f"sk-mock-{self._next_key_id}"
            self._next_key_id += 1
            if alias is not None:
                self.minted_aliases.add(alias)
            return httpx.Response(200, json={"key": key, "models": body["models"], "key_alias": alias})
        if path == "/key/delete" and request.method == "POST":
            for alias in body.get("key_aliases", []):
                self.minted_aliases.discard(alias)
            return httpx.Response(200, json={"deleted_keys": body.get("key_aliases", [])})
        return httpx.Response(404)


def _patch_gateway(monkeypatch, gw: _MockGateway) -> None:
    """Points every `httpx.Client(...)` call AND every bare `httpx.post(...)` call `gateway_sync` makes
    at `gw` instead of the network - `sync_agent_model_groups` uses a `Client`, `mint_virtual_key` a bare
    `post()`. Captures the real objects *before* patching - `httpx` is one shared module object, so
    patching `app.core.gateway_sync.httpx.Client`/`.post` also changes what a later call in this file's
    own code would resolve to; calling the saved reference avoids the fake client recursively calling
    itself."""
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("base_url", None)
        return real_client(*args, transport=httpx.MockTransport(gw.handler), base_url=GATEWAY_URL, **kwargs)

    def fake_post(url, **kwargs):
        if gw.fail:
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))
        # Routed through a real `httpx.Client`/`MockTransport` pair (not a bare `gw.handler(...)` call) so
        # the returned `Response` has its `.request` set - `raise_for_status()` needs it, and a bare call
        # leaves it unset (verified directly: that raises `RuntimeError`, not the intended HTTPStatusError).
        with real_client(transport=httpx.MockTransport(gw.handler)) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr("app.core.gateway_sync.httpx.Client", fake_client)
    monkeypatch.setattr("app.core.gateway_sync.httpx.post", fake_post)
    monkeypatch.setenv("EVAL_GATEWAY_ADMIN_KEY", "admin-key")


@pytest.fixture
def mock_gateway(monkeypatch):
    gw = _MockGateway()
    _patch_gateway(monkeypatch, gw)
    return gw


# ------------------------------------------------------------------ 3.1 to_litellm_params
def test_bare_name_translates_to_ollama_chat(session):
    params = to_litellm_params(session, "qwen3:8b", None, _settings())
    assert params == {"model": "ollama_chat/qwen3:8b", "api_base": "http://ollama.local"}


def test_cloud_ref_translates_using_the_registered_provider(session):
    repo.create_provider(
        session,
        kind="openai",
        name="openai-main",
        key_env="OPENAI_MAIN_KEY",
        base_url=None,
        ack_at=None,
    )
    params = to_litellm_params(session, "@openai-main/gpt-4o", None, _settings())
    assert params == {"model": "openai/gpt-4o", "api_key": "os.environ/OPENAI_MAIN_KEY"}


def test_azure_openai_ref_uses_the_azure_litellm_prefix_and_api_version(session):
    repo.create_provider(
        session,
        kind="azure-openai",
        name="azure-main",
        key_env="AZURE_MAIN_KEY",
        base_url="https://my-resource.openai.azure.com",
        ack_at=None,
        api_version="2024-10-21",
    )
    params = to_litellm_params(session, "@azure-main/gpt-4o-deployment", None, _settings())
    assert params == {
        "model": "azure/gpt-4o-deployment",
        "api_key": "os.environ/AZURE_MAIN_KEY",
        "api_base": "https://my-resource.openai.azure.com",
        "api_version": "2024-10-21",
    }


def test_registered_ollama_ref_uses_ollama_chat_prefix_and_no_key(session):
    """`add-ollama-provider-kind`: a model registered under an `ollama`-kind provider syncs to the gateway the
    same way a bare local name does (`ollama_chat/<model>`) - no `api_key` at all, since there is none."""
    repo.create_provider(
        session,
        kind="ollama",
        name="ollama-main",
        key_env=None,
        base_url="http://my-ollama-server:11434",
        ack_at=None,
    )
    params = to_litellm_params(session, "@ollama-main/qwen3:8b", None, _settings())
    assert params == {"model": "ollama_chat/qwen3:8b", "api_base": "http://my-ollama-server:11434"}
    assert "api_key" not in params


def test_registered_ollama_ref_without_a_base_url_falls_back_to_the_configured_default(session):
    repo.create_provider(session, kind="ollama", name="ollama-main", key_env=None, base_url=None, ack_at=None)
    params = to_litellm_params(session, "@ollama-main/qwen3:8b", None, _settings())
    assert params == {"model": "ollama_chat/qwen3:8b", "api_base": "http://ollama.local"}


def test_params_are_merged_into_the_translated_litellm_params(session):
    params = to_litellm_params(session, "qwen3:8b", {"temperature": 0.2}, _settings())
    assert params["temperature"] == 0.2


def test_unregistered_provider_raises(session):
    with pytest.raises(ValueError, match="no registered provider"):
        to_litellm_params(session, "@no-such-provider/gpt-4o", None, _settings())


# ------------------------------------------------------------------ 3.2 sync_agent_model_groups: create/update/delete
def test_sync_creates_a_group_per_declared_model(session, mock_gateway):
    agent = _agent(session, {"reasoning": "qwen3:8b", "generation": "gemma4:e4b"})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results == {"reasoning": {"status": "ok"}, "generation": {"status": "ok"}}
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {
        "my-reasoner__reasoning",
        "my-reasoner__generation",
    }
    creates = [c for c in mock_gateway.calls if c[1] == "/model/new"]
    assert len(creates) == 2


def test_sync_updates_an_existing_group_instead_of_duplicating_it(session, mock_gateway):
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    sync_agent_model_groups(session, agent, _settings())
    agent.declared_models = {"reasoning": "gemma4:e4b"}
    session.flush()
    results = sync_agent_model_groups(session, agent, _settings())
    assert results == {"reasoning": {"status": "ok"}}
    assert len(mock_gateway.db_models) == 1  # updated in place, not duplicated
    (deployment,) = mock_gateway.db_models.values()
    assert deployment["litellm_params"]["model"] == "ollama_chat/gemma4:e4b"
    updates = [c for c in mock_gateway.calls if c[1] == "/model/update"]
    assert len(updates) == 1


def test_sync_removes_a_group_for_a_dropped_task_type(session, mock_gateway):
    agent = _agent(session, {"reasoning": "qwen3:8b", "generation": "gemma4:e4b"})
    sync_agent_model_groups(session, agent, _settings())
    agent.declared_models = {"reasoning": "qwen3:8b"}
    session.flush()
    results = sync_agent_model_groups(
        session, agent, _settings(), previous_declared_models={"reasoning": "qwen3:8b", "generation": "gemma4:e4b"}
    )
    assert results["generation"] == {"status": "ok"}
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {"my-reasoner__reasoning"}


def test_sync_refuses_to_override_a_statically_configured_group(session, monkeypatch):
    gw = _MockGateway(static_groups=["my-reasoner__reasoning"])
    _patch_gateway(monkeypatch, gw)
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["reasoning"]["status"] == "error"
    assert "statically configured" in results["reasoning"]["detail"]


# ------------------------------------------------------------------ 3.3 unreachable gateway never raises
def test_unreachable_gateway_returns_an_error_result_without_raising(session, monkeypatch):
    _patch_gateway(monkeypatch, _MockGateway(fail=True))
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    results = sync_agent_model_groups(session, agent, _settings())  # must not raise
    assert results["reasoning"]["status"] == "error"


def test_no_gateway_configured_is_skipped_not_an_error(session):
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    results = sync_agent_model_groups(session, agent, Settings())  # gateway_url unset
    assert results == {"*": {"status": "skipped", "detail": "no gateway configured (EVAL_GATEWAY_URL unset)"}}


def test_no_admin_credential_is_skipped_not_an_error(session, monkeypatch):
    monkeypatch.delenv("EVAL_GATEWAY_ADMIN_KEY", raising=False)
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["*"]["status"] == "skipped"


# ------------------------------------------------------------------ add-declared-model-fallback
def test_fallback_group_name_is_distinct_from_the_primary_and_stable():
    name = fallback_group_name("my-reasoner", "reasoning")
    assert name == "my-reasoner__reasoning__fallback"
    assert name != model_group_name("my-reasoner", "reasoning")
    assert fallback_group_name("my-reasoner", "reasoning") == name  # stable across calls


def test_sync_creates_a_fallback_group_alongside_the_primary(session, mock_gateway):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["reasoning"] == {"status": "ok"}
    assert results["reasoning__fallback"] == {"status": "ok"}
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {
        "my-reasoner__reasoning",
        "my-reasoner__reasoning__fallback",
    }


def test_sync_updates_the_existing_fallback_group_instead_of_duplicating_it(session, mock_gateway):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}})
    sync_agent_model_groups(session, agent, _settings())
    agent.declared_models = {"reasoning": {"model": "qwen3:8b", "fallback": "qwen3:14b"}}
    session.flush()
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["reasoning__fallback"] == {"status": "ok"}
    assert len(mock_gateway.db_models) == 2  # still exactly one primary + one fallback, not three
    fallback_deployment = mock_gateway.db_models[
        next(mid for mid, m in mock_gateway.db_models.items() if m["model_name"] == "my-reasoner__reasoning__fallback")
    ]
    assert fallback_deployment["litellm_params"]["model"] == "ollama_chat/qwen3:14b"


def test_sync_removes_the_fallback_group_when_fallback_is_cleared_but_task_type_remains(session, mock_gateway):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}})
    sync_agent_model_groups(session, agent, _settings())
    agent.declared_models = {"reasoning": "qwen3:8b"}
    session.flush()
    results = sync_agent_model_groups(
        session,
        agent,
        _settings(),
        previous_declared_models={"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}},
    )
    assert results["reasoning__fallback"] == {"status": "ok"}
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {"my-reasoner__reasoning"}


def test_sync_removes_the_fallback_group_when_its_task_type_is_removed(session, mock_gateway):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}, "generation": "qwen3:8b"})
    sync_agent_model_groups(session, agent, _settings())
    agent.declared_models = {"generation": "qwen3:8b"}
    session.flush()
    results = sync_agent_model_groups(
        session,
        agent,
        _settings(),
        previous_declared_models={
            "reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"},
            "generation": "qwen3:8b",
        },
    )
    assert results["reasoning"] == {"status": "ok"}
    assert results["reasoning__fallback"] == {"status": "ok"}
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {"my-reasoner__generation"}


def test_sync_reports_a_broken_fallback_reference_as_an_error_without_deleting_any_existing_group(
    session, mock_gateway
):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}})
    sync_agent_model_groups(session, agent, _settings())  # fallback group now exists and is working
    agent.declared_models = {"reasoning": {"model": "qwen3:8b", "fallback": "@no-such-provider/gpt-4o"}}
    session.flush()
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["reasoning"] == {"status": "ok"}
    assert results["reasoning__fallback"]["status"] == "error"
    assert "no registered provider" in results["reasoning__fallback"]["detail"]
    # the previously-synced fallback group is left exactly as it was - mirrors how a broken primary
    # reference also leaves any existing group untouched rather than deleting it
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {
        "my-reasoner__reasoning",
        "my-reasoner__reasoning__fallback",
    }


def test_sync_result_keys_distinguish_primary_and_fallback_outcomes(session, mock_gateway):
    agent = _agent(session, {"reasoning": {"model": "qwen3:8b", "fallback": "gemma4:e4b"}})
    results = sync_agent_model_groups(session, agent, _settings())
    assert set(results) == {"reasoning", "reasoning__fallback"}


# ------------------------------------------------------------------ 3.4 provider credential never sent literally
def test_provider_credential_is_never_sent_as_a_literal_value(session, mock_gateway):
    repo.create_provider(
        session,
        kind="openai",
        name="openai-main",
        key_env="OPENAI_MAIN_KEY",
        base_url=None,
        ack_at=None,
    )
    agent = _agent(session, {"default": "@openai-main/gpt-4o"})
    sync_agent_model_groups(session, agent, _settings())
    (deployment,) = mock_gateway.db_models.values()
    assert deployment["litellm_params"]["api_key"] == "os.environ/OPENAI_MAIN_KEY"
    # the literal provider key value was never generated/held anywhere in this flow to begin with - there is
    # no key material in the test fixture at all, so its absence from every gateway call is definitional; this
    # assertion guards the *reference*, which is the part that could regress into a literal by mistake
    for _method, _path, body in mock_gateway.calls:
        if body:
            assert json.dumps(body).count("OPENAI_MAIN_KEY") <= 1  # only the os.environ/ reference, nowhere else


# ------------------------------------------------------------------ add-custom-model-provider-kind
def test_custom_kind_declared_model_is_not_gateway_routed_not_an_error(session, mock_gateway):
    repo.create_provider(
        session, kind="custom", name="context-classifier", key_env=None, base_url="http://127.0.0.1:8765", ack_at=None
    )
    agent = _agent(session, {"classification": "@context-classifier/classify"})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results == {
        "classification": {
            "status": "not_gateway_routed",
            "detail": "custom-kind model; not routed through the gateway",
        }
    }
    assert mock_gateway.db_models == {}  # no deployment ever created for it


def test_custom_kind_alongside_a_normal_task_type_only_the_custom_one_is_skipped(session, mock_gateway):
    repo.create_provider(
        session, kind="custom", name="context-classifier", key_env=None, base_url="http://127.0.0.1:8765", ack_at=None
    )
    agent = _agent(session, {"reasoning": "qwen3:8b", "classification": "@context-classifier/classify"})
    results = sync_agent_model_groups(session, agent, _settings())
    assert results["reasoning"] == {"status": "ok"}
    assert results["classification"]["status"] == "not_gateway_routed"
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {"my-reasoner__reasoning"}


def test_switching_a_task_type_from_gateway_routed_to_custom_removes_its_old_group(session, mock_gateway):
    agent = _agent(session, {"classification": "qwen3:8b"})
    sync_agent_model_groups(session, agent, _settings())
    assert {m["model_name"] for m in mock_gateway.db_models.values()} == {"my-reasoner__classification"}

    repo.create_provider(
        session, kind="custom", name="context-classifier", key_env=None, base_url="http://127.0.0.1:8765", ack_at=None
    )
    agent.declared_models = {"classification": "@context-classifier/classify"}
    session.flush()
    results = sync_agent_model_groups(
        session, agent, _settings(), previous_declared_models={"classification": "qwen3:8b"}
    )
    assert results["classification"]["status"] == "not_gateway_routed"
    assert mock_gateway.db_models == {}  # the old gateway-routed group was removed, not left orphaned


def test_a_fallback_declared_alongside_a_custom_kind_primary_is_also_never_gateway_routed(session, mock_gateway):
    repo.create_provider(
        session, kind="custom", name="context-classifier", key_env=None, base_url="http://127.0.0.1:8765", ack_at=None
    )
    agent = _agent(
        session,
        {"classification": {"model": "@context-classifier/classify", "fallback": "qwen3:8b"}},
    )
    results = sync_agent_model_groups(session, agent, _settings())
    assert results == {
        "classification": {
            "status": "not_gateway_routed",
            "detail": "custom-kind model; not routed through the gateway",
        }
    }
    assert mock_gateway.db_models == {}  # neither the primary nor its fallback ever gets a gateway deployment


# ------------------------------------------------------------------ add-agent-playground: virtual-key minting
def test_agent_gateway_group_names_includes_primary_and_fallback(session):
    agent = _agent(
        session,
        {
            "reasoning": {"model": "qwen3:8b", "fallback": "gemma3:4b"},
            "generation": "qwen3:8b",
        },
    )
    names = agent_gateway_group_names(session, agent)
    assert set(names) == {
        model_group_name("my-reasoner", "reasoning"),
        fallback_group_name("my-reasoner", "reasoning"),
        model_group_name("my-reasoner", "generation"),
    }


def test_agent_gateway_group_names_skips_custom_kind_tasks(session):
    repo.create_provider(
        session, kind="custom", name="context-classifier", key_env=None, base_url="http://127.0.0.1:8765", ack_at=None
    )
    agent = _agent(session, {"classification": "@context-classifier/classify", "routing": "qwen3:8b"})
    names = agent_gateway_group_names(session, agent)
    assert names == [model_group_name("my-reasoner", "routing")]


def test_mint_virtual_key_posts_scoped_groups_and_returns_the_key(session, monkeypatch):
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, json={"key": "sk-minted"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.core.gateway_sync.httpx.post", fake_post)
    monkeypatch.setenv("EVAL_GATEWAY_ADMIN_KEY", "admin-key")
    result = mint_virtual_key(session, agent, _settings())
    assert result.status == "ok"
    assert result.key == "sk-minted"
    assert captured["url"] == f"{GATEWAY_URL}/key/generate"
    assert captured["json"] == {"models": [model_group_name("my-reasoner", "reasoning")], "key_alias": "my-reasoner"}
    assert captured["headers"] == {"Authorization": "Bearer admin-key"}


def test_mint_virtual_key_is_skipped_without_a_configured_gateway(session):
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    result = mint_virtual_key(session, agent, Settings())
    assert result.status == "skipped"
    assert result.key is None


def test_mint_virtual_key_is_skipped_without_an_admin_key(session, monkeypatch):
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    monkeypatch.delenv("EVAL_GATEWAY_ADMIN_KEY", raising=False)
    result = mint_virtual_key(session, agent, _settings())
    assert result.status == "skipped"


def test_mint_virtual_key_clears_a_previous_key_under_the_same_alias_before_re_minting(session, mock_gateway):
    """Found live: litellm enforces globally unique `key_alias` values, so a second mint for the
    same agent (re-enabling playground, rotating, or a declared-model change re-mint) used to 400
    with "Key with alias '...' already exists" - this agent's alias is never new on a re-mint."""
    agent = _agent(session, {"reasoning": "qwen3:8b"})
    first = mint_virtual_key(session, agent, _settings())
    assert first.status == "ok"

    second = mint_virtual_key(session, agent, _settings())
    assert second.status == "ok"
    assert second.key != first.key  # a genuinely fresh key, not the same one reused

    # A pre-delete runs before every mint, unconditionally (simpler and more robust than parsing
    # litellm's own error text to detect "alias already exists" reactively) - the first is a no-op
    # (nothing minted yet under this alias), the second actually clears the first mint's key.
    delete_calls = [c for c in mock_gateway.calls if c[1] == "/key/delete"]
    assert len(delete_calls) == 2
    assert all(c[2] == {"key_aliases": ["my-reasoner"]} for c in delete_calls)


def test_mint_virtual_key_reports_a_failure_without_raising(session, monkeypatch):
    agent = _agent(session, {"reasoning": "qwen3:8b"})

    def fake_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.core.gateway_sync.httpx.post", fake_post)
    monkeypatch.setenv("EVAL_GATEWAY_ADMIN_KEY", "admin-key")
    result = mint_virtual_key(session, agent, _settings())
    assert result.status == "error"
    assert result.key is None
