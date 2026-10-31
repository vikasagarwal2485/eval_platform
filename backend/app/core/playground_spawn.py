"""Spawns a playground-eligible agent's real catalog script as a one-shot subprocess
(`add-agent-playground`, design.md D1/D5) - never a reimplementation of that script's own logic.

The sole intended caller of `app.core.secrets.decrypt` outside its own module (enforced by
`tests/test_secrets.py`): every stored playground credential is decrypted here, in-process,
immediately before it is handed to the subprocess that needs it, and nowhere else.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app import repo
from app.config import Settings
from app.core import agent_catalog
from app.core.gateway_sync import agent_slug, fallback_group_name
from app.core.secrets import decrypt
from app.models import Agent
from app.schemas import declared_model_fallback_ref, declared_model_ref

DEFAULT_SPAWN_TIMEOUT_S = 300.0

# Task types a reasoning/router-flavor agent may configure a fallback for, and the CLI flag name
# each one's fallback maps to on that flavor's own script - "<task>-fallback-group" for every
# reasoning task, but only "routing" for the router (its "classification" task is a custom-kind,
# non-gateway-routed dependency with no fallback-group concept at all).
_FALLBACK_TASKS_BY_KIND: dict[str, list[str]] = {
    "reasoning": ["classification", "reasoning", "generation"],
    "router": ["routing"],
    "chatbot": [],
}


class SpawnError(Exception):
    """A spawn could not even be started - surfaced by the caller as a clear 4xx, never a 500."""


class AgentBusy(SpawnError):
    """A second spawn was requested while one for this agent is already in flight (spec
    `agent-playground`: 'A second spawn is rejected while one is already running')."""


# Agent ids with a spawn currently in flight - in-memory and process-local, the same scope every
# other piece of in-process state in this codebase already has (e.g. `app.core.events`' hub).
_in_flight: set[int] = set()


@dataclass(frozen=True)
class SpawnResult:
    status: str  # "ok" | "timeout" | "error"
    returncode: int | None = None
    stderr: str | None = None


def _decrypt_credentials(agent: Agent, settings: Settings) -> tuple[str, str | None]:
    """`(ingest_token, gateway_key)` for `agent`, decrypted - `gateway_key` is `None` only when
    none was ever minted/stored (e.g. the gateway was unreachable when this agent was made
    eligible); a flavor that needs one checks for that itself."""
    if not agent.playground_eligible:
        raise SpawnError(f"agent '{agent.name}' is not playground-eligible")
    if not settings.playground_secret_key:
        raise SpawnError("EVAL_SECRET_KEY is not configured; playground credential storage is off")
    if agent.playground_ingest_token_enc is None:
        raise SpawnError(f"agent '{agent.name}' has no stored ingest token to spawn with")
    token = decrypt(agent.playground_ingest_token_enc, secret_key=settings.playground_secret_key)
    key = None
    if agent.playground_gateway_key_enc is not None:
        key = decrypt(agent.playground_gateway_key_enc, secret_key=settings.playground_secret_key)
    return token, key


def _resolve_interpreter(flavor_root: Path) -> str:
    """The agents' own venv interpreter - never the backend's `sys.executable`, which has none of
    `agents/requirements.txt`'s dependencies (litellm/langchain/mcp/...) installed."""
    venv_python = flavor_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    raise SpawnError(
        f"no agents interpreter found at {venv_python} - run 'make agents-setup' from the repo root"
    )


def _fallback_flags(agent: Agent, flavor: agent_catalog.AgentFlavor, slug: str) -> list[str]:
    flags: list[str] = []
    for task_type in _FALLBACK_TASKS_BY_KIND.get(flavor.kind, []):
        entry = (agent.declared_models or {}).get(task_type)
        if entry is not None and declared_model_fallback_ref(entry) is not None:
            flags += [f"--{task_type}-fallback-group", fallback_group_name(slug, task_type)]
    return flags


# For each hand-off target kind a router flavor's script can use (`AgentFlavor.handoff_kinds`), the CLI
# flag that hands it the target's own decrypted ingest token, and (when not `None`) the flag for its own
# decrypted gateway virtual key - `chatbot.py` never talks to the gateway, so a `chatbot`-kind target has
# no corresponding gateway-key flag at all, unlike a `reasoning`-kind one (`add-chatbot-handoff`).
_HANDOFF_FLAGS_BY_KIND: dict[str, tuple[str, str | None]] = {
    "reasoning": ("--reasoning-agent-token", "--reasoning-agent-gateway-key"),
    "chatbot": ("--chatbot-agent-token", None),
}


def _router_handoff_flags(
    session: Session, agent: Agent, flavor: agent_catalog.AgentFlavor, settings: Settings
) -> list[str]:
    """Resolves `agent`'s own configured `handoff_agent_names` against `flavor.handoff_kinds` - at
    most one target of each kind the flavor's script actually knows how to use, flagged with that
    kind's own credential flags (`_HANDOFF_FLAGS_BY_KIND`). A target whose kind isn't in
    `flavor.handoff_kinds` at all (e.g. another `router`) is accepted by the registry but has nothing
    this script can do with it, so it's simply skipped here rather than erroring - only an *ambiguous*
    configuration (more than one target of the *same* usable kind) is rejected, since the script has
    no way to pick between them."""
    handoff_names = agent.handoff_agent_names or []
    if not handoff_names:
        raise SpawnError(f"agent '{agent.name}' has no handoff_agent_names configured")

    targets_by_kind: dict[str, Agent] = {}
    for name in handoff_names:
        target = repo.get_agent_by_name(session, name)
        if target is None:
            raise SpawnError(f"hand-off target '{name}' no longer exists")
        if target.kind not in flavor.handoff_kinds:
            continue
        existing = targets_by_kind.get(target.kind)
        if existing is not None:
            raise SpawnError(
                f"agent '{agent.name}' has more than one '{target.kind}'-kind handoff_agent_names entry "
                f"('{existing.name}' and '{target.name}'), but the '{flavor.id}' flavor's script can only "
                f"use one hand-off target of each kind"
            )
        targets_by_kind[target.kind] = target

    if not targets_by_kind:
        raise SpawnError(
            f"agent '{agent.name}' has no handoff_agent_names entry of a kind the '{flavor.id}' flavor's "
            f"script can use ({', '.join(flavor.handoff_kinds) or 'none'})"
        )

    argv: list[str] = []
    for kind, target in targets_by_kind.items():
        token_flag, gateway_key_flag = _HANDOFF_FLAGS_BY_KIND[kind]
        target_token, target_key = _decrypt_credentials(target, settings)
        argv += [token_flag, target_token]
        if gateway_key_flag is not None:
            if not target_key:
                raise SpawnError(f"hand-off target '{target.name}' has no stored gateway virtual key")
            argv += [gateway_key_flag, target_key]
    return argv


def build_argv(
    session: Session,
    agent: Agent,
    flavor: agent_catalog.AgentFlavor,
    settings: Settings,
    *,
    system_prompt: str | None,
    skills: list[str],
    task: str,
) -> list[str]:
    """The exact argv a terminal operator would type for `agent`'s cataloged script, assembled from
    its own registration (declared models' fallback groups, decrypted spawn credentials) and this
    request's prompt/skills/task (design.md D5). Every flavor is driven through self-discovery
    (`--token` alone resolves its gateway group names / custom-provider endpoints) - this never
    passes an explicit model-group override, mirroring how a terminal operator would normally run
    these scripts unless pointing at a different agent's groups on purpose."""
    ingest_token, gateway_key = _decrypt_credentials(agent, settings)
    interpreter = _resolve_interpreter(agent_catalog.flavor_root(flavor))
    argv = [interpreter, *flavor.entrypoint[1:]]
    argv += ["--platform-url", settings.platform_self_url, "--token", ingest_token]

    if flavor.kind == "chatbot":
        default_ref = (agent.declared_models or {}).get("default")
        if default_ref is None:
            raise SpawnError(f"agent '{agent.name}' has no 'default' declared model to spawn with")
        argv += ["--model", declared_model_ref(default_ref), "--ollama-url", settings.ollama_base_url]
    else:
        if not settings.gateway_url:
            raise SpawnError("no gateway configured (EVAL_GATEWAY_URL unset); cannot spawn a gateway-routed agent")
        if not gateway_key:
            raise SpawnError(f"agent '{agent.name}' has no stored gateway virtual key to spawn with")
        argv += ["--gateway-url", settings.gateway_url, "--gateway-key", gateway_key]
        argv += _fallback_flags(agent, flavor, agent_slug(agent.name))

    if flavor.kind == "router":
        argv += _router_handoff_flags(session, agent, flavor, settings)

    if settings.otel_endpoint:
        argv += ["--otel-endpoint", settings.otel_endpoint]
    if system_prompt:
        argv += ["--system-prompt", system_prompt]
    for skill in skills:
        argv += ["--skill", skill]
    argv += ["--task", task]
    return argv


async def spawn_agent(
    session: Session,
    agent: Agent,
    settings: Settings,
    *,
    system_prompt: str | None,
    skills: list[str],
    task: str,
    timeout_s: float = DEFAULT_SPAWN_TIMEOUT_S,
) -> SpawnResult:
    """Launches `agent`'s cataloged script as a one-shot subprocess and waits for it to finish (or
    be killed on timeout). The spawned process reports its own turn through the ordinary ingest
    path - this function's return value only ever describes the *process* (did it start, finish
    cleanly, time out), never the turn's own content; the caller already has that via the existing
    live-event feed (design.md D6)."""
    if agent.id in _in_flight:
        raise AgentBusy(f"agent '{agent.name}' already has a spawn in progress")
    flavor = agent_catalog.get_flavor(agent.flavor or "")
    if flavor is None:
        raise SpawnError(f"agent '{agent.name}' has no valid catalog flavor configured")

    argv = build_argv(session, agent, flavor, settings, system_prompt=system_prompt, skills=skills, task=task)
    cwd = agent_catalog.flavor_root(flavor)

    _in_flight.add(agent.id)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return SpawnResult("timeout")
        if proc.returncode != 0:
            return SpawnResult(
                "error", returncode=proc.returncode, stderr=stderr.decode("utf-8", "replace")[-2000:]
            )
        return SpawnResult("ok", returncode=0)
    finally:
        _in_flight.discard(agent.id)
