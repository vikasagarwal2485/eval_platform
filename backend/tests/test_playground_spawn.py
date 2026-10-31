"""`app.core.playground_spawn` (add-agent-playground): argv assembly and subprocess supervision,
against fakes only - no real agent process is ever launched here."""

from __future__ import annotations

import asyncio

import pytest

from app import repo
from app.config import Settings
from app.core import agent_catalog, playground_spawn
from app.core.secrets import encrypt
from app.models import Agent

SECRET_KEY = "a-test-passphrase"


def _settings(**over) -> Settings:
    base = dict(
        gateway_url="http://gateway.local",
        ollama_base_url="http://ollama.local",
        playground_secret_key=SECRET_KEY,
        platform_self_url="http://platform.local",
    )
    base.update(over)
    return Settings(**base)


def _agent(session, *, name="bot", kind="chatbot", declared_models=None, flavor=None, **over) -> Agent:
    a = Agent(
        name=name,
        kind=kind,
        declared_models=declared_models if declared_models is not None else {"default": "qwen3:8b"},
        status="active",
        token_hash="h",
        token_prefix="p",
        eval_config={},
        provider_acks={},
        playground_eligible=True,
        flavor=flavor or kind,
        playground_ingest_token_enc=encrypt("ingest-tok", secret_key=SECRET_KEY),
        **over,
    )
    session.add(a)
    session.flush()
    return a


def _with_gateway_key(agent: Agent, key: str = "sk-gw-key") -> Agent:
    agent.playground_gateway_key_enc = encrypt(key, secret_key=SECRET_KEY)
    return agent


def _fake_flavor_root(monkeypatch, tmp_path, flavor_id: str):
    """Points `agent_catalog.flavor_root` at a fake directory with a stub `.venv/bin/python` for one
    flavor id, so `build_argv` can resolve an interpreter without touching the real `agents/.venv`."""
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()

    real_flavor_root = agent_catalog.flavor_root

    def fake(flavor):
        return tmp_path if flavor.id == flavor_id else real_flavor_root(flavor)

    monkeypatch.setattr(playground_spawn.agent_catalog, "flavor_root", fake)
    return venv_python


# ------------------------------------------------------------------ build_argv: chatbot flavor
def test_build_argv_chatbot_uses_model_and_ollama_url_not_the_gateway(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session, declared_models={"default": "qwen3:8b"})
    flavor = agent_catalog.get_flavor("chatbot")
    argv = playground_spawn.build_argv(
        session, agent, flavor, _settings(), system_prompt=None, skills=[], task="hi"
    )
    assert "--model" in argv and argv[argv.index("--model") + 1] == "qwen3:8b"
    assert "--ollama-url" in argv and argv[argv.index("--ollama-url") + 1] == "http://ollama.local"
    assert "--gateway-url" not in argv
    assert "--token" in argv and argv[argv.index("--token") + 1] == "ingest-tok"
    assert "--task" in argv and argv[-1] == "hi"


def test_build_argv_chatbot_requires_a_default_declared_model(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session, declared_models={})
    flavor = agent_catalog.get_flavor("chatbot")
    with pytest.raises(playground_spawn.SpawnError, match="default"):
        playground_spawn.build_argv(session, agent, flavor, _settings(), system_prompt=None, skills=[], task="hi")


# ------------------------------------------------------------------ build_argv: reasoning flavor
def test_build_argv_reasoning_uses_gateway_and_omits_model(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "reasoning")
    agent = _with_gateway_key(
        _agent(
            session, kind="reasoning",
            declared_models={"classification": "qwen3:8b", "reasoning": "qwen3:8b", "generation": "qwen3:8b"},
        )
    )
    flavor = agent_catalog.get_flavor("reasoning")
    argv = playground_spawn.build_argv(
        session, agent, flavor, _settings(), system_prompt=None, skills=[], task="2+2?"
    )
    assert "--gateway-url" in argv and argv[argv.index("--gateway-url") + 1] == "http://gateway.local"
    assert "--gateway-key" in argv and argv[argv.index("--gateway-key") + 1] == "sk-gw-key"
    assert "--model" not in argv  # self-discovery, not an explicit override


def test_build_argv_reasoning_adds_fallback_group_flags_when_configured(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "reasoning")
    agent = _with_gateway_key(
        _agent(
            session, name="my-reasoner", kind="reasoning",
            declared_models={
                "classification": "qwen3:8b",
                "reasoning": {"model": "qwen3:8b", "fallback": "gemma3:4b"},
                "generation": "qwen3:8b",
            },
        )
    )
    flavor = agent_catalog.get_flavor("reasoning")
    argv = playground_spawn.build_argv(
        session, agent, flavor, _settings(), system_prompt=None, skills=[], task="2+2?"
    )
    assert "--reasoning-fallback-group" in argv
    idx = argv.index("--reasoning-fallback-group")
    assert argv[idx + 1] == "my-reasoner__reasoning__fallback"
    assert "--generation-fallback-group" not in argv
    assert "--classification-fallback-group" not in argv


def test_build_argv_reasoning_requires_a_stored_gateway_key(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "reasoning")
    agent = _agent(session, kind="reasoning", declared_models={"reasoning": "qwen3:8b"})  # no gateway key stored
    flavor = agent_catalog.get_flavor("reasoning")
    with pytest.raises(playground_spawn.SpawnError, match="gateway virtual key"):
        playground_spawn.build_argv(session, agent, flavor, _settings(), system_prompt=None, skills=[], task="x")


def test_build_argv_requires_a_configured_gateway_for_a_gateway_routed_flavor(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "reasoning")
    agent = _with_gateway_key(_agent(session, kind="reasoning", declared_models={"reasoning": "qwen3:8b"}))
    flavor = agent_catalog.get_flavor("reasoning")
    with pytest.raises(playground_spawn.SpawnError, match="gateway"):
        playground_spawn.build_argv(
            session, agent, flavor, _settings(gateway_url=None), system_prompt=None, skills=[], task="x"
        )


# ------------------------------------------------------------------ build_argv: router flavor + hand-off
def test_build_argv_router_includes_handoff_credentials(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    target = _with_gateway_key(
        _agent(session, name="reasoner", kind="reasoning", declared_models={"reasoning": "qwen3:8b"}),
        key="sk-target-key",
    )
    target.playground_ingest_token_enc = encrypt("target-ingest-tok", secret_key=SECRET_KEY)
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router",
            declared_models={"routing": "qwen3:8b", "classification": "qwen3:8b"},
            handoff_agent_names=["reasoner"],
        ),
        key="sk-router-key",
    )
    flavor = agent_catalog.get_flavor("router")
    argv = playground_spawn.build_argv(
        session, router, flavor, _settings(), system_prompt=None, skills=[], task="route this"
    )
    assert "--reasoning-agent-token" in argv
    assert argv[argv.index("--reasoning-agent-token") + 1] == "target-ingest-tok"
    assert "--reasoning-agent-gateway-key" in argv
    assert argv[argv.index("--reasoning-agent-gateway-key") + 1] == "sk-target-key"


def test_build_argv_router_rejects_two_handoff_agents_of_the_same_kind(session, monkeypatch, tmp_path):
    """The registry allows more than one hand-off agent on a router; the `router` flavor's own script
    (classifier_router_agent.py) can only use at most one target of each kind it knows about
    (catalog.yaml's `handoff_kinds: [reasoning, chatbot]`) - two of the *same* kind is ambiguous."""
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    first = _with_gateway_key(
        _agent(session, name="reasoner-a", kind="reasoning", declared_models={"reasoning": "qwen3:8b"}),
        key="sk-a",
    )
    first.playground_ingest_token_enc = encrypt("tok-a", secret_key=SECRET_KEY)
    _with_gateway_key(
        _agent(session, name="reasoner-b", kind="reasoning", declared_models={"reasoning": "qwen3:8b"}),
        key="sk-b",
    )
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router",
            declared_models={"routing": "qwen3:8b", "classification": "qwen3:8b"},
            handoff_agent_names=["reasoner-a", "reasoner-b"],
        ),
        key="sk-router-key",
    )
    flavor = agent_catalog.get_flavor("router")
    with pytest.raises(playground_spawn.SpawnError, match="more than one 'reasoning'-kind"):
        playground_spawn.build_argv(
            session, router, flavor, _settings(), system_prompt=None, skills=[], task="route this"
        )


def test_build_argv_router_wires_both_a_reasoning_and_a_chatbot_handoff_target(session, monkeypatch, tmp_path):
    """add-chatbot-handoff: a router may configure one hand-off agent of each kind the flavor's
    script knows about - both get their own credential flags, with the chatbot target getting no
    gateway-key flag at all (chatbot.py never talks to the gateway)."""
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    reasoner = _with_gateway_key(
        _agent(session, name="reasoner", kind="reasoning", declared_models={"reasoning": "qwen3:8b"}),
        key="sk-reasoner",
    )
    reasoner.playground_ingest_token_enc = encrypt("reasoner-tok", secret_key=SECRET_KEY)
    chatbot = _agent(session, name="bot", kind="chatbot", declared_models={"default": "qwen3:8b"})
    chatbot.playground_ingest_token_enc = encrypt("chatbot-tok", secret_key=SECRET_KEY)
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router",
            declared_models={"routing": "qwen3:8b", "classification": "qwen3:8b"},
            handoff_agent_names=["reasoner", "bot"],
        ),
        key="sk-router-key",
    )
    flavor = agent_catalog.get_flavor("router")
    argv = playground_spawn.build_argv(
        session, router, flavor, _settings(), system_prompt=None, skills=[], task="route this"
    )
    assert argv[argv.index("--reasoning-agent-token") + 1] == "reasoner-tok"
    assert argv[argv.index("--reasoning-agent-gateway-key") + 1] == "sk-reasoner"
    assert argv[argv.index("--chatbot-agent-token") + 1] == "chatbot-tok"
    assert "--chatbot-agent-gateway-key" not in argv


def test_build_argv_router_skips_a_handoff_target_of_a_kind_the_flavor_cannot_use(session, monkeypatch, tmp_path):
    """A hand-off target the registry accepted but this flavor's script has nothing to do with (e.g.
    another `router`) is skipped rather than erroring, as long as at least one usable target remains."""
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    reasoner = _with_gateway_key(
        _agent(session, name="reasoner", kind="reasoning", declared_models={"reasoning": "qwen3:8b"}),
        key="sk-reasoner",
    )
    reasoner.playground_ingest_token_enc = encrypt("reasoner-tok", secret_key=SECRET_KEY)
    _agent(session, name="other-router", kind="router", declared_models={"routing": "qwen3:8b"})
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router",
            declared_models={"routing": "qwen3:8b", "classification": "qwen3:8b"},
            handoff_agent_names=["reasoner", "other-router"],
        ),
        key="sk-router-key",
    )
    flavor = agent_catalog.get_flavor("router")
    argv = playground_spawn.build_argv(
        session, router, flavor, _settings(), system_prompt=None, skills=[], task="route this"
    )
    assert argv[argv.index("--reasoning-agent-token") + 1] == "reasoner-tok"
    assert "--chatbot-agent-token" not in argv


def test_build_argv_router_requires_handoff_agent_names(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    router = _with_gateway_key(_agent(session, name="router", kind="router", declared_models={"routing": "x"}))
    flavor = agent_catalog.get_flavor("router")
    with pytest.raises(playground_spawn.SpawnError, match="handoff_agent_names"):
        playground_spawn.build_argv(
            session, router, flavor, _settings(), system_prompt=None, skills=[], task="x"
        )


def test_build_argv_router_requires_a_handoff_target_of_a_usable_kind(session, monkeypatch, tmp_path):
    """Every configured hand-off agent is of a kind the flavor's script cannot use at all - rejected
    with a clear error, rather than silently spawning with no hand-off credentials at all."""
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    _agent(session, name="other-router", kind="router", declared_models={"routing": "qwen3:8b"})
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router", declared_models={"routing": "x"},
            handoff_agent_names=["other-router"],
        )
    )
    flavor = agent_catalog.get_flavor("router")
    with pytest.raises(playground_spawn.SpawnError, match="no handoff_agent_names entry of a kind"):
        playground_spawn.build_argv(
            session, router, flavor, _settings(), system_prompt=None, skills=[], task="x"
        )


def test_build_argv_router_requires_the_handoff_target_to_be_playground_eligible(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "router")
    target = repo.get_agent_by_name(session, "reasoner") or Agent(
        name="reasoner", kind="reasoning", declared_models={"reasoning": "x"}, status="active",
        token_hash="h", token_prefix="p", eval_config={}, provider_acks={}, playground_eligible=False,
    )
    session.add(target)
    session.flush()
    router = _with_gateway_key(
        _agent(
            session, name="router", kind="router", declared_models={"routing": "x"},
            handoff_agent_names=["reasoner"],
        )
    )
    flavor = agent_catalog.get_flavor("router")
    with pytest.raises(playground_spawn.SpawnError, match="not playground-eligible"):
        playground_spawn.build_argv(
            session, router, flavor, _settings(), system_prompt=None, skills=[], task="x"
        )


# ------------------------------------------------------------------ build_argv: common bits
def test_build_argv_includes_system_prompt_and_skills_in_order(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session)
    flavor = agent_catalog.get_flavor("chatbot")
    argv = playground_spawn.build_argv(
        session, agent, flavor, _settings(), system_prompt="be terse", skills=["a", "b"], task="hi",
    )
    assert "--system-prompt" in argv and argv[argv.index("--system-prompt") + 1] == "be terse"
    skill_positions = [i for i, v in enumerate(argv) if v == "--skill"]
    assert [argv[i + 1] for i in skill_positions] == ["a", "b"]


def test_build_argv_omits_system_prompt_flag_when_not_given(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session)
    flavor = agent_catalog.get_flavor("chatbot")
    argv = playground_spawn.build_argv(
        session, agent, flavor, _settings(), system_prompt=None, skills=[], task="hi",
    )
    assert "--system-prompt" not in argv


def test_build_argv_raises_when_not_playground_eligible(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session)
    agent.playground_eligible = False
    flavor = agent_catalog.get_flavor("chatbot")
    with pytest.raises(playground_spawn.SpawnError, match="not playground-eligible"):
        playground_spawn.build_argv(session, agent, flavor, _settings(), system_prompt=None, skills=[], task="x")


def test_build_argv_raises_without_a_configured_secret_key(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session)
    flavor = agent_catalog.get_flavor("chatbot")
    with pytest.raises(playground_spawn.SpawnError, match="EVAL_SECRET_KEY"):
        playground_spawn.build_argv(
            session, agent, flavor, _settings(playground_secret_key=None), system_prompt=None, skills=[], task="x",
        )


def test_resolve_interpreter_raises_a_clear_error_when_the_venv_is_missing(tmp_path):
    with pytest.raises(playground_spawn.SpawnError, match="agents-setup"):
        playground_spawn._resolve_interpreter(tmp_path)


# ------------------------------------------------------------------ spawn_agent: process supervision
class _FakeProcess:
    def __init__(self, returncode: int, stderr: bytes = b"", hang: bool = False):
        self.returncode = returncode
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10)
        return b"", self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def _patch_subprocess(monkeypatch, proc: _FakeProcess):
    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(playground_spawn.asyncio, "create_subprocess_exec", fake_exec)


async def test_spawn_agent_returns_ok_on_clean_exit(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    _patch_subprocess(monkeypatch, _FakeProcess(0))
    agent = _agent(session)
    result = await playground_spawn.spawn_agent(
        session, agent, _settings(), system_prompt=None, skills=[], task="hi"
    )
    assert result.status == "ok"
    assert agent.id not in playground_spawn._in_flight  # lock released


async def test_spawn_agent_reports_nonzero_exit_as_error(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    _patch_subprocess(monkeypatch, _FakeProcess(1, stderr=b"boom"))
    agent = _agent(session)
    result = await playground_spawn.spawn_agent(
        session, agent, _settings(), system_prompt=None, skills=[], task="hi"
    )
    assert result.status == "error"
    assert result.returncode == 1
    assert "boom" in result.stderr


async def test_spawn_agent_times_out_and_kills_the_process(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    proc = _FakeProcess(0, hang=True)
    _patch_subprocess(monkeypatch, proc)
    agent = _agent(session)
    result = await playground_spawn.spawn_agent(
        session, agent, _settings(), system_prompt=None, skills=[], task="hi", timeout_s=0.01,
    )
    assert result.status == "timeout"
    assert proc.killed
    assert agent.id not in playground_spawn._in_flight


async def test_spawn_agent_rejects_a_concurrent_spawn_for_the_same_agent(session, monkeypatch, tmp_path):
    _fake_flavor_root(monkeypatch, tmp_path, "chatbot")
    agent = _agent(session)
    playground_spawn._in_flight.add(agent.id)
    try:
        with pytest.raises(playground_spawn.AgentBusy):
            await playground_spawn.spawn_agent(
                session, agent, _settings(), system_prompt=None, skills=[], task="hi"
            )
    finally:
        playground_spawn._in_flight.discard(agent.id)
