"""Reference classifier-routed multi-agent orchestrator (`add-classifier-router-agent`, spec
`reference-agents`).

Per turn: (1) **classify** the problem via an external, non-LLM context-classifier service
(`https://github.com/vikasagarwal2485/llms/tree/main/classifier_model`'s `POST /classify`) - a `tool` span,
not an `llm` span, explicitly exempt from the gateway-only constraint below; (2) **route** - a single
gateway-routed LLM call, given the classifier's result, that must call the `resolve_route` tool (over MCP)
to decide what happens next - the tool's own result *is* the routing decision, not anything the LLM says
afterwards; (3) **act** - either finish the turn immediately with a canned response and no further model
call (the "short_circuit" branch), or hand the problem off to one of two kinds of separately-registered
subprocess (the "handoff" branch, `add-chatbot-handoff`): the existing `reasoning_agent.py`, for a problem
the routing-mapping tool judged needs multi-step reasoning, or `chatbot.py`, for one it judged simple enough
for a single-call chatbot. The routing decision's `target_kind` (`"reasoning"`, the default for backward
compatibility, or `"chatbot"`) picks which; `--reasoning-agent-token`/`--chatbot-agent-token` each name
*which* registered agent that handoff actually runs as, independently of the routing decision itself - see
their own help text. An unmapped classification result ends the turn in a visible error rather than
guessing a branch; so does a routing decision that wants a hand-off kind this run was never given
credentials for.

Built with LangGraph (a small `StateGraph`: classify -> route -> a conditional edge to short_circuit/handoff/
no_match) and LangChain's `ChatOpenAI` for the one real LLM call this agent makes. That call is never made
directly against a provider: `ChatOpenAI` is pointed at the shared gateway (`base_url`/`api_key`), addressed
by a task-scoped model group ("routing") this agent discovers for itself at startup - exactly like every
other reference agent's calls - with a configurable fallback group. Unlike `reasoning_agent.py`'s litellm-based
`call_llm()`, `ChatOpenAI` needs no `openai/` prefix hack to reach the gateway (verified live while building
this agent - see design.md Decision 3); its concrete model is read from the `x-litellm-model-name` response
header (`include_response_headers=True`), and a fallback group is passed via `extra_body={"fallbacks": [...]}`
(design.md Decision 4).

**Both the classifier's address and the routing model group are self-discovered** (`add-agent-self-discovery`,
`add-custom-model-provider-kind`): this agent calls the platform's `GET /api/ingest/v1/whoami` with its own
`--token` and uses whatever `gateway_model_groups`/`custom_model_endpoints` it computed for this agent's
actual registered name - so this works correctly no matter what the agent is registered as.
`--routing-model-group`/`--classifier-url` are **overrides** - passing one skips discovery for that one thing
entirely and uses exactly what was given. If discovery itself fails (platform unreachable, bad token) and no
override was given, the agent falls back to hardcoded defaults and prints a visible warning, rather than
failing to start.

`--routing-fallback-group` (`add-declared-model-fallback`) names a gateway group to fall back to if the
routing call's primary group is unreachable - unset by default.

The reasoning-handoff branch spawns `agents/reasoning_agent.py` as its own subprocess, with its own
platform token/gateway key (`--reasoning-agent-token`/`--reasoning-agent-gateway-key`) - that subprocess
registers its own turn, under its own agent identity, fully gateway-routed exactly as already proven. The
chatbot-handoff branch (`add-chatbot-handoff`) likewise spawns `agents/chatbot.py` as its own subprocess,
with its own platform token (`--chatbot-agent-token`) - `chatbot.py` never talks to the gateway at all (no
corresponding gateway-key flag exists for it), so it's spawned with a plain Ollama URL instead
(`--chatbot-agent-ollama-url`). `chatbot.py` itself has no self-discovery of its own model (unlike
`reasoning_agent.py`'s group-name discovery), so this agent discovers the chatbot target's declared model
on its behalf via `whoami()`, using the target's own token, and passes it explicitly as `--model`. Either
flag is optional - a run that never needs a given hand-off kind need not supply credentials for it, but a
routing decision that *does* want that kind without the matching flag ends the turn in a visible error.
This orchestrator's own turn records the hand-off and its result as a `tool` span, never the sub-agent's own
LLM spans.

Usage:
    # the normal case - routing group and classifier address are discovered from this agent's own registration:
    python -m classifier_router_agent --platform-url http://localhost:8000 --token <ingest-token> \
        --gateway-url http://localhost:4000 --gateway-key <this-agent's-virtual-key> \
        --reasoning-agent-token <reasoning-agent's-ingest-token> \
        --reasoning-agent-gateway-key <reasoning-agent's-virtual-key> \
        --chatbot-agent-token <chatbot-agent's-ingest-token> \
        --problem "Apple stock surged today after a strong earnings report."
    # override discovery (e.g. to point this run at a different agent's group, or a different classifier):
    python -m classifier_router_agent --platform-url ... --token ... --gateway-url ... --gateway-key ... \
        --routing-model-group my-router__routing --classifier-url http://127.0.0.1:9999 \
        --reasoning-agent-token ... --reasoning-agent-gateway-key ... --problem "..."
    # with a configured fallback for the routing call:
    python -m classifier_router_agent --platform-url ... --token ... --gateway-url ... --gateway-key ... \
        --routing-fallback-group my-router__routing__fallback \
        --reasoning-agent-token ... --reasoning-agent-gateway-key ... --problem "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

import httpx
import openai
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent_sdk import AgentClient, whoami  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parent

# The gateway's Router model group this agent uses by default (`add-litellm-gateway-infra`'s convention),
# and the context-classifier's default address (confirmed live at this address while drafting this change) -
# both hardcoded only as a last-resort fallback for when self-discovery itself fails; see the module docstring.
ROUTING_MODEL_GROUP = "classifier-router-agent__routing"
DEFAULT_CLASSIFIER_URL = "http://127.0.0.1:8765"

RESOLVE_ROUTE_TOOL = "resolve_route"
ROUTING_SYSTEM_PROMPT = (
    "You are a routing assistant for an AI agent platform. You will be given a context-classifier's result "
    "for one problem, as a JSON object keyed by classifier task. Call the resolve_route tool exactly once, "
    "passing that exact JSON object as its `classification` argument, to decide what should happen next. Do "
    "not call any other tool, and do not call resolve_route more than once."
)


class RoutingToolNotCalled(RuntimeError):
    """The routing LLM did not call `resolve_route` - a visible error for that turn, never guessed (design.md
    Risks)."""


class NoRouteMatched(RuntimeError):
    """The routing-mapping tool found no matching rule for this classification result (spec `reference-agents`:
    "An unmapped classification result does not guess a target")."""


# ------------------------------------------------------------------ classify (non-LLM, gateway-exempt)
def classify(classifier_url: str, problem: str, *, timeout: float = 30.0) -> dict:
    """One HTTP call to the external context-classifier service's `/classify` (design.md Context: a local,
    pre-trained multi-task text classifier - not a generative model, makes no LLM API call of its own, and is
    explicitly exempt from this agent's gateway-only constraint). Returns the `results` object: `{task:
    {"label": ..., "confidence": ..., "probabilities": {...}}}`."""
    resp = httpx.post(f"{classifier_url}/classify", json={"text": problem}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["results"]


# ------------------------------------------------------------------ resolve_route (MCP tool call)
def _mcp_server_params() -> StdioServerParameters:
    """The routing-mapping MCP server, spawned as a subprocess over stdio (design.md Decision 6) - this
    agent is the MCP client and owns that subprocess's lifecycle for exactly as long as resolving one turn's
    routing decision takes."""
    return StdioServerParameters(command=sys.executable, args=["-m", "routing_mcp.server"], cwd=str(AGENTS_DIR))


async def _call_resolve_route(classification: dict) -> dict:
    async with stdio_client(_mcp_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(RESOLVE_ROUTE_TOOL, {"classification": classification})
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            return json.loads(text)


def call_resolve_route(classification: dict) -> dict:
    return asyncio.run(_call_resolve_route(classification))


# ------------------------------------------------------------------ routing decision (one LLM call, one tool call)
def _concrete_model(resp, requested_model: str) -> str:
    """The real deployment that answered a gateway-routed call, not the group alias - mirrors
    reasoning_agent.py's `_concrete_model`, but reads `ChatOpenAI`'s own `x-litellm-model-name` response
    header directly (via `include_response_headers=True`), with no `llm_provider-` prefix digging needed -
    that prefix is specific to litellm's raw `completion()` client, not `ChatOpenAI` (verified live while
    building this agent). Falls back to the requested model string when the header isn't present, so a span
    is never left without a model."""
    headers = (resp.response_metadata or {}).get("headers") or {}
    return headers.get("x-litellm-model-name") or requested_model


def _usage(resp) -> dict:
    tu = (resp.response_metadata or {}).get("token_usage") or {}
    return {"prompt_tokens": tu.get("prompt_tokens"), "completion_tokens": tu.get("completion_tokens")}


def make_routing_llm(
    gateway_url: str, gateway_key: str, model: str, *, fallback_group: str | None = None, timeout: float = 60.0
) -> ChatOpenAI:
    """A `ChatOpenAI` pointed at the shared gateway - no `openai/` prefix needed (design.md Decision 3)."""
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": gateway_url,
        "api_key": gateway_key,
        "timeout": timeout,
        "include_response_headers": True,
    }
    if fallback_group:
        # The gateway's `fallbacks` field is litellm-proxy-specific, not standard OpenAI chat-completions -
        # `extra_body` passes it through verbatim (design.md Decision 4, verified live against the gateway).
        kwargs["extra_body"] = {"fallbacks": [fallback_group]}
    return ChatOpenAI(**kwargs)


def routing_decision(
    llm: ChatOpenAI, classification: dict, call_tool=call_resolve_route, *, system_prompt: str | None = None,
) -> tuple[dict, str, dict]:
    """The bounded routing step: one LLM call (bound with the `resolve_route` tool, required to call it),
    executing only the first tool call it requests, and using that tool's own return value directly as the
    final routing decision (design.md Decision 5 - revised during implementation to drop an earlier draft's
    confirmatory second LLM call: every scenario in spec `reference-agents` is satisfied by the tool's own
    result, without depending on a model to correctly restate a JSON object verbatim).

    Returns `(decision, concrete_model, usage)` - the concrete model and usage are this one LLM call's,
    recorded as the turn's single "routing" span; `call_tool` is injectable for tests.

    `system_prompt` (`add-agent-playground`) overrides the hardcoded `ROUTING_SYSTEM_PROMPT` when
    given - unset by default, matching this agent's behavior before this parameter existed."""
    tool_schema = {
        "type": "function",
        "function": {
            "name": RESOLVE_ROUTE_TOOL,
            "description": "Resolve a context-classifier result to a concrete downstream routing action.",
            "parameters": {
                "type": "object",
                "properties": {"classification": {"type": "object"}},
                "required": ["classification"],
            },
        },
    }
    messages = [SystemMessage(system_prompt or ROUTING_SYSTEM_PROMPT), HumanMessage(json.dumps(classification))]
    response = llm.bind_tools([tool_schema]).invoke(messages)
    if not response.tool_calls:
        raise RoutingToolNotCalled("the routing model did not call resolve_route")
    call = response.tool_calls[0]  # only the first requested call is ever executed - never more than one
    decision = call_tool(call["args"].get("classification", classification))
    model = _concrete_model(response, llm.model_name)
    return decision, model, _usage(response)


# ------------------------------------------------------------------ handoff (reasoning branch)
def spawn_reasoning_agent(
    problem: str,
    *,
    platform_url: str,
    reasoning_agent_token: str,
    gateway_url: str,
    reasoning_agent_gateway_key: str,
    otel_endpoint: str | None = None,
    timeout: float = 600.0,
) -> str:
    """Spawns `reasoning_agent.py` as its own subprocess (design.md Decision 8), with its own
    platform/gateway credentials - it registers its own, separate turn under its own agent identity, fully
    gateway-routed exactly as already proven; this orchestrator's own turn never attributes its spans or
    trace (add-otel-tracing: a separate process means a genuinely separate `AgentClient`/trace too, not
    merely a separate platform turn - there is no shared trace context to pass across a subprocess
    boundary, nor any need to). Its `--problem` mode prints exactly the final answer to stdout and nothing
    else on success (its own `run_once()`), so the whole captured, stripped stdout is that answer."""
    cmd = [
        sys.executable,
        "-m",
        "reasoning_agent",
        "--platform-url",
        platform_url,
        "--token",
        reasoning_agent_token,
        "--gateway-url",
        gateway_url,
        "--gateway-key",
        reasoning_agent_gateway_key,
        "--problem",
        problem,
    ]
    if otel_endpoint:
        cmd += ["--otel-endpoint", otel_endpoint]
    result = subprocess.run(cmd, cwd=str(AGENTS_DIR), capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"reasoning_agent exited with {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


# ------------------------------------------------------------------ handoff (chatbot branch, add-chatbot-handoff)
def _discover_chatbot_model(platform_url: str, token: str) -> str | None:
    """The chatbot hand-off target's own declared model, discovered on its behalf via `whoami()` using
    *its* token (not this router's own) - `chatbot.py` itself has no self-discovery of its own model
    (unlike `reasoning_agent.py`'s group-name discovery), so this agent discovers it instead, the same
    best-effort way `_discover_agent_name()` discovers the target's name. Falls back to `None` (letting
    `chatbot.py`'s own hardcoded `--model` default apply) when discovery fails or the target declares no
    `default` model - never blocks the handoff."""
    try:
        declared = whoami(platform_url, token).get("declared_models") or {}
    except httpx.HTTPError:
        return None
    entry = declared.get("default")
    if entry is None:
        return None
    return entry.get("model") if isinstance(entry, dict) else entry


def spawn_chatbot_agent(
    problem: str,
    *,
    platform_url: str,
    chatbot_agent_token: str,
    ollama_url: str = "http://localhost:11434",
    model: str | None = None,
    otel_endpoint: str | None = None,
    timeout: float = 600.0,
) -> str:
    """Spawns `agents/chatbot.py` as its own subprocess, mirroring `spawn_reasoning_agent()`'s design
    (design.md D8) - its own platform credentials, registering its own, separate turn under its own
    agent identity. Unlike the reasoning branch, `chatbot.py` never talks to the gateway (it has no
    `--gateway-key` flag at all), so this is spawned with a plain Ollama URL rather than gateway
    credentials. `model` is the hand-off target's own discovered declared model
    (`_discover_chatbot_model()`); when `None`, `chatbot.py`'s own hardcoded default applies instead, so
    this still starts rather than failing on a discovery miss."""
    cmd = [
        sys.executable,
        "-m",
        "chatbot",
        "--platform-url",
        platform_url,
        "--token",
        chatbot_agent_token,
        "--ollama-url",
        ollama_url,
        "--task",
        problem,
    ]
    if model:
        cmd += ["--model", model]
    if otel_endpoint:
        cmd += ["--otel-endpoint", otel_endpoint]
    result = subprocess.run(cmd, cwd=str(AGENTS_DIR), capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"chatbot exited with {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


# ------------------------------------------------------------------ the graph
class RouterState(TypedDict, total=False):
    turn: Any  # eval_agent_sdk.Turn - spans are recorded directly from inside each node
    problem: str
    classifier_url: str
    llm: Any  # ChatOpenAI bound to the routing group
    platform_url: str
    reasoning_agent_token: str | None
    gateway_url: str
    reasoning_agent_gateway_key: str | None
    chatbot_agent_token: str | None  # add-chatbot-handoff
    chatbot_agent_ollama_url: str  # add-chatbot-handoff
    handoff_otel_endpoint: str | None  # forwarded as-is to whichever hand-off subprocess is spawned
    classification: dict
    decision: dict
    final_answer: str
    system_prompt: str | None


def _classify_node(state: RouterState) -> dict:
    classification = classify(state["classifier_url"], state["problem"])
    # `model` (add-otel-tracing): the classifier is a model/service of its own (a `custom`-kind provider,
    # not a generative one - design.md Context) - naming the endpoint that answered here, the same way an
    # `llm_call()` names its model, makes it visible which service this tool call actually went to.
    state["turn"].tool_call(
        name="classify", args={"text": state["problem"]}, result=json.dumps(classification),
        model=state["classifier_url"],
        description="Multi-task text classifier resolving the problem to per-task labels/probabilities",
    )
    return {"classification": classification}


def _route_node(state: RouterState) -> dict:
    # `call_tool=call_resolve_route` is passed explicitly (not left to routing_decision()'s own default)
    # so it resolves this module global at call time, not def time - letting tests monkeypatch
    # `call_resolve_route` and have it actually take effect here.
    decision, model, usage = routing_decision(
        state["llm"], state["classification"], call_tool=call_resolve_route,
        system_prompt=state.get("system_prompt"),
    )
    state["turn"].llm_call(
        model=model,
        output=json.dumps(decision),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        kind="routing",
    )
    return {"decision": decision}


def _after_route(state: RouterState) -> str:
    action = state["decision"].get("action")
    return action if action in ("short_circuit", "handoff") else "no_match"


def _short_circuit_node(state: RouterState) -> dict:
    final = state["decision"].get("response", "")
    state["turn"].tool_call(
        name="short_circuit", args=state["decision"], result=final,
        description="Answers directly from the routing decision, without handing off to another agent",
    )
    return {"final_answer": final}


def _missing_handoff_credentials_error(target_kind: str) -> RuntimeError:
    flag = "--reasoning-agent-token/--reasoning-agent-gateway-key" if target_kind == "reasoning" else (
        "--chatbot-agent-token"
    )
    return RuntimeError(
        f"the routing decision wants a '{target_kind}' hand-off target, but {flag} "
        f"was not given to this run"
    )


def _handoff_node(state: RouterState) -> dict:
    decision = state["decision"]
    # `target_kind` (add-chatbot-handoff) picks which kind of hand-off target this decision wants -
    # "reasoning" is the default when a routing rule omits it, matching this agent's behavior before
    # this field existed (every existing `routes.yaml` rule, and any other rule set written before
    # this change, still resolves to the reasoning branch unchanged).
    target_kind = decision.get("target_kind", "reasoning")
    if target_kind == "reasoning":
        token, gateway_key = state.get("reasoning_agent_token"), state.get("reasoning_agent_gateway_key")
        if not token or not gateway_key:
            raise _missing_handoff_credentials_error(target_kind)
    elif target_kind == "chatbot":
        token = state.get("chatbot_agent_token")
        if not token:
            raise _missing_handoff_credentials_error(target_kind)
    else:
        raise ValueError(f"routing decision named an unsupported hand-off target_kind: {target_kind!r}")

    # The routing-mapping tool's own `target_agent` is a static config label (e.g. a hardcoded
    # "reasoning-agent"), not this handoff's actual destination - whichever agent the registry
    # resolved this kind's token to could be registered under any name (e.g. "discovery-agent").
    # Discovered here via the same best-effort `whoami()` this agent already uses for its own
    # identity, using the *target's* token instead of this router's own - never blocks the handoff
    # on failure; falls back to the tool's own static label rather than leaving it blank.
    target_agent_name = _discover_agent_name(state["platform_url"], token)
    span_args = {**decision, "target_agent": target_agent_name or decision.get("target_agent")}
    name = f"handoff_to_{target_kind}_agent"
    description = f"Spawns the reference {target_kind} agent as a subprocess and returns its final answer"
    try:
        if target_kind == "reasoning":
            final = spawn_reasoning_agent(
                state["problem"],
                platform_url=state["platform_url"],
                reasoning_agent_token=token,
                gateway_url=state["gateway_url"],
                reasoning_agent_gateway_key=gateway_key,
                otel_endpoint=state.get("handoff_otel_endpoint"),
            )
        else:
            chatbot_model = _discover_chatbot_model(state["platform_url"], token)
            final = spawn_chatbot_agent(
                state["problem"],
                platform_url=state["platform_url"],
                chatbot_agent_token=token,
                ollama_url=state.get("chatbot_agent_ollama_url") or "http://localhost:11434",
                model=chatbot_model,
                otel_endpoint=state.get("handoff_otel_endpoint"),
            )
    except Exception as exc:
        state["turn"].tool_call(name=name, args=span_args, error=str(exc), description=description)
        raise
    state["turn"].tool_call(name=name, args=span_args, result=final, description=description)
    return {"final_answer": final}


def _no_match_node(state: RouterState) -> dict:
    raise NoRouteMatched(f"no route matched for classification result: {state['classification']!r}")


def build_graph():
    g = StateGraph(RouterState)
    g.add_node("classify", _classify_node)
    g.add_node("route", _route_node)
    g.add_node("short_circuit", _short_circuit_node)
    g.add_node("handoff", _handoff_node)
    g.add_node("no_match", _no_match_node)
    g.set_entry_point("classify")
    g.add_edge("classify", "route")
    g.add_conditional_edges(
        "route", _after_route, {"short_circuit": "short_circuit", "handoff": "handoff", "no_match": "no_match"}
    )
    g.add_edge("short_circuit", END)
    g.add_edge("handoff", END)
    g.add_edge("no_match", END)
    return g.compile()


# ------------------------------------------------------------------ one turn
def solve_one(
    client: AgentClient,
    session_id: str,
    gateway_url: str,
    gateway_key: str,
    problem: str,
    *,
    routing_group: str = ROUTING_MODEL_GROUP,
    routing_fallback_group: str | None = None,
    classifier_url: str = DEFAULT_CLASSIFIER_URL,
    platform_url: str,
    reasoning_agent_token: str | None = None,
    reasoning_agent_gateway_key: str | None = None,
    chatbot_agent_token: str | None = None,
    chatbot_agent_ollama_url: str = "http://localhost:11434",
    handoff_otel_endpoint: str | None = None,
    reference: str | None = None,
    system_prompt: str | None = None,
) -> str:
    graph = build_graph()
    llm = make_routing_llm(gateway_url, gateway_key, routing_group, fallback_group=routing_fallback_group)
    with client.turn(session_id, input=problem, reference=reference, system_prompt=system_prompt) as t:
        result = graph.invoke(
            {
                "turn": t,
                "problem": problem,
                "classifier_url": classifier_url,
                "llm": llm,
                "platform_url": platform_url,
                "reasoning_agent_token": reasoning_agent_token,
                "gateway_url": gateway_url,
                "reasoning_agent_gateway_key": reasoning_agent_gateway_key,
                "chatbot_agent_token": chatbot_agent_token,
                "chatbot_agent_ollama_url": chatbot_agent_ollama_url,
                "handoff_otel_endpoint": handoff_otel_endpoint,
                "system_prompt": system_prompt,
            }
        )
        final = result["final_answer"]
        t.finish(final)
    return final


# ------------------------------------------------------------------ self-discovery
def _resolve_routing_group_and_classifier_url(
    platform_url: str, token: str, explicit_group: str | None, explicit_classifier_url: str | None
) -> tuple[str, str]:
    """The routing gateway group name and the classifier's address for this run (design.md Decisions 2 and
    9 - a single-task analogue of `reasoning_agent.py`'s `_resolve_model_groups()`, extended to also resolve
    a `custom`-kind dependency's address via `whoami()`'s `custom_model_endpoints`
    (`add-custom-model-provider-kind`), rather than only a gateway group name). An explicit override always
    wins for its own value and is never second-guessed; when both are already explicit, `whoami()` isn't
    called at all. Otherwise calls `whoami()` once and uses its `gateway_model_groups`/`custom_model_endpoints`
    for whichever value has no explicit override. If that call itself fails, prints a visible warning and
    falls back to the hardcoded defaults for any value still unresolved - the agent still starts either way."""
    if explicit_group is not None and explicit_classifier_url is not None:
        return explicit_group, explicit_classifier_url

    discovered: dict = {}
    try:
        discovered = whoami(platform_url, token)
    except httpx.HTTPError as exc:
        print(
            f"warning: could not discover this agent's routing group/classifier address ({exc}); falling "
            f"back to {ROUTING_MODEL_GROUP!r}/{DEFAULT_CLASSIFIER_URL!r} for whatever wasn't explicitly set",
            file=sys.stderr,
        )

    routing_group = explicit_group or discovered.get("gateway_model_groups", {}).get("routing") or ROUTING_MODEL_GROUP
    classifier_entry = discovered.get("custom_model_endpoints", {}).get("classification") or {}
    classifier_url = explicit_classifier_url or classifier_entry.get("base_url") or DEFAULT_CLASSIFIER_URL
    return routing_group, classifier_url


# ------------------------------------------------------------------ CLI
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reference classifier-routed multi-agent orchestrator")
    p.add_argument("--platform-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--gateway-url", default="http://localhost:4000")
    p.add_argument("--gateway-key", required=True, help="This agent's own gateway virtual key.")
    p.add_argument(
        "--routing-model-group",
        default=None,
        help="Gateway model group for the routing call. Omit (the default) to discover this agent's own "
        f"group from the platform at startup (`add-agent-self-discovery`), falling back to "
        f"{ROUTING_MODEL_GROUP!r} if discovery fails. Pass this to override discovery entirely.",
    )
    p.add_argument(
        "--routing-fallback-group",
        default=None,
        help="Gateway model group to fall back to (`add-declared-model-fallback`) if the routing call's "
        "primary group is unreachable - passed as that request's own 'fallbacks' field. Unset by default.",
    )
    p.add_argument(
        "--classifier-url",
        default=None,
        help="Base URL of the external context-classifier service. Omit (the default) to discover it from "
        f"this agent's own registration (`add-custom-model-provider-kind`), falling back to "
        f"{DEFAULT_CLASSIFIER_URL!r} if discovery fails. Pass this to override discovery entirely.",
    )
    p.add_argument(
        "--reasoning-agent-token",
        default=None,
        help="The reasoning hand-off target's own ingest token. Required only if a routing decision can "
        "actually resolve to target_kind 'reasoning' (the default when a routing rule omits target_kind) - "
        "omitting it ends such a turn in a visible error rather than silently failing the handoff.",
    )
    p.add_argument(
        "--reasoning-agent-gateway-key",
        default=None,
        help="The reasoning hand-off target's own gateway virtual key. See --reasoning-agent-token.",
    )
    p.add_argument(
        "--chatbot-agent-token",
        default=None,
        help="The chatbot hand-off target's own ingest token (add-chatbot-handoff). Required only if a "
        "routing decision can resolve to target_kind 'chatbot' - omitting it ends such a turn in a "
        "visible error rather than silently failing the handoff. chatbot.py never talks to the gateway, "
        "so it has no corresponding gateway-key flag.",
    )
    p.add_argument(
        "--chatbot-agent-ollama-url",
        default="http://localhost:11434",
        help="Ollama base URL the chatbot hand-off target is spawned against (add-chatbot-handoff). "
        "Matches chatbot.py's own --ollama-url default.",
    )
    # add-otel-tracing: unset (the default, or EVAL_OTEL_ENDPOINT also unset) is a graceful no-op.
    # Also forwarded to the spawned reasoning-agent subprocess on a handoff, so both agents' spans
    # land under their own separate traces in the same Collector/Tempo - point it at e.g.
    # http://localhost:4317. Falls back to EVAL_OTEL_ENDPOINT - the same env var the platform
    # backend itself reads - so setting it once in a shell configures both without needing this
    # flag repeated (the spawned subprocess also inherits this process's environment, so it would
    # pick up EVAL_OTEL_ENDPOINT on its own too - the explicit forward below still matters when
    # --otel-endpoint was passed as a flag rather than via the environment).
    p.add_argument(
        "--otel-endpoint",
        default=os.environ.get("EVAL_OTEL_ENDPOINT"),
        help="OTLP gRPC endpoint for real tracing, e.g. localhost:4317 (default: $EVAL_OTEL_ENDPOINT)",
    )
    p.add_argument(
        "--system-prompt",
        default=None,
        help="Overrides the hardcoded ROUTING_SYSTEM_PROMPT for the routing-decision call "
        "(add-agent-playground). Unset by default.",
    )
    p.add_argument(
        "--skill",
        action="append",
        default=[],
        dest="skills",
        metavar="NAME",
        help="Fetch a named skill's instructions from the platform and prepend them to "
        "--system-prompt (add-agent-playground). Repeatable; applied in the order given.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--problem", dest="problem", help="A single problem to answer.")
    g.add_argument(
        "--task", dest="problem",
        help="Alias for --problem (add-agent-playground - a uniform one-shot input flag across every "
        "catalog flavor).",
    )
    return p


def run_once(
    client: AgentClient,
    gateway_url: str,
    gateway_key: str,
    problem: str,
    *,
    routing_group: str,
    routing_fallback_group: str | None,
    classifier_url: str,
    platform_url: str,
    reasoning_agent_token: str | None = None,
    reasoning_agent_gateway_key: str | None = None,
    chatbot_agent_token: str | None = None,
    chatbot_agent_ollama_url: str = "http://localhost:11434",
    handoff_otel_endpoint: str | None = None,
    system_prompt: str | None = None,
) -> None:
    import uuid

    session_id = uuid.uuid4().hex
    try:
        final = solve_one(
            client,
            session_id,
            gateway_url,
            gateway_key,
            problem,
            routing_group=routing_group,
            routing_fallback_group=routing_fallback_group,
            classifier_url=classifier_url,
            platform_url=platform_url,
            reasoning_agent_token=reasoning_agent_token,
            reasoning_agent_gateway_key=reasoning_agent_gateway_key,
            chatbot_agent_token=chatbot_agent_token,
            chatbot_agent_ollama_url=chatbot_agent_ollama_url,
            handoff_otel_endpoint=handoff_otel_endpoint,
            system_prompt=system_prompt,
        )
    except (openai.OpenAIError, httpx.HTTPError, RoutingToolNotCalled, NoRouteMatched, RuntimeError) as exc:
        # Covers: a gateway/LLM failure (never silently retried direct against a provider, bypassing the
        # gateway), the classifier being unreachable, the routing model not calling the tool, no route
        # matching, and the reasoning-agent subprocess failing - every one fails the turn visibly.
        raise SystemExit(f"error answering this problem: {exc}") from exc
    print(final)


def _discover_agent_name(platform_url: str, token: str) -> str | None:
    """This agent's own registered name (add-otel-tracing: used for `gen_ai.agent.name` on each turn's
    root span) - a separate, best-effort `whoami()` call (never blocks startup on failure), kept apart
    from `_resolve_routing_group_and_classifier_url()`'s own discovery call above so that function's
    tested return shape (exactly the group name and classifier URL) stays unchanged."""
    try:
        return whoami(platform_url, token).get("name")
    except httpx.HTTPError:
        return None


def _fetch_skill(platform_url: str, token: str, name: str) -> str:
    """One skill's instructions, by name (`add-agent-playground`) - see `chatbot.py`'s identical
    helper; duplicated rather than shared, matching this module's existing `_discover_agent_name()`
    duplication convention."""
    try:
        resp = httpx.get(
            f"{platform_url.rstrip('/')}/api/ingest/v1/skills/{name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SystemExit(f"could not fetch skill '{name}': {exc.response.status_code} {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise SystemExit(f"could not fetch skill '{name}': {exc}") from exc
    return resp.json()["instructions"]


def compose_system_prompt(base_prompt: str | None, skill_instructions: list[str]) -> str | None:
    """Prepends each skill's instructions, in the order given, ahead of `base_prompt` - see
    `chatbot.py`'s identical helper. Returns `None` when there is neither a base prompt nor any
    skill, so `routing_decision()` falls back to the hardcoded `ROUTING_SYSTEM_PROMPT`, exactly as
    before this flag existed."""
    parts = [*skill_instructions, base_prompt] if base_prompt else list(skill_instructions)
    parts = [p for p in parts if p]
    return "\n\n".join(parts) if parts else None


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    skill_instructions = [_fetch_skill(args.platform_url, args.token, name) for name in args.skills]
    system_prompt = compose_system_prompt(args.system_prompt, skill_instructions)
    routing_group, classifier_url = _resolve_routing_group_and_classifier_url(
        args.platform_url, args.token, args.routing_model_group, args.classifier_url
    )
    client = AgentClient(
        args.platform_url,
        args.token,
        otel_endpoint=args.otel_endpoint,
        service_name="classifier-router-agent",
        agent_name=_discover_agent_name(args.platform_url, args.token),
        # A real LangGraph `StateGraph` (classify -> route -> short_circuit/handoff) run for every
        # turn - a genuine workflow/graph, unlike chatbot.py's single call.
        workflow_name="classifier-router-graph",
    )
    try:
        run_once(
            client,
            args.gateway_url,
            args.gateway_key,
            args.problem,
            routing_group=routing_group,
            routing_fallback_group=args.routing_fallback_group,
            classifier_url=classifier_url,
            platform_url=args.platform_url,
            reasoning_agent_token=args.reasoning_agent_token,
            reasoning_agent_gateway_key=args.reasoning_agent_gateway_key,
            chatbot_agent_token=args.chatbot_agent_token,
            chatbot_agent_ollama_url=args.chatbot_agent_ollama_url,
            handoff_otel_endpoint=args.otel_endpoint,
            system_prompt=system_prompt,
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
