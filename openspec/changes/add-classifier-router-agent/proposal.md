# Proposal

## Why

Every reference agent the platform ships today (`chatbot.py`, `reasoning_agent.py`) is a single agent that
makes its own LLM calls directly through the shared gateway; none of them delegate work to *another* agent, and
none use a real agentic-framework (LangChain/LangGraph) orchestration pattern with tool-calling. The user wants
to validate that pattern specifically - classify first (via an already-running, external, non-LLM classifier
service), let an LLM-driven routing step decide what to do with the result via a tool call, and then hand off to
a different, independently-running agent for the actual task - while still proving every real LLM call in the
new agent is gateway-routed, with no direct provider call anywhere, exactly like the existing reference agents.

## What Changes

- New reference agent (`agents/classifier_router_agent.py`), built with LangChain/LangGraph, registered with the
  platform the same way `reasoning_agent.py` is (own name, ingest token, self-discovery via `whoami`, kind
  `reasoning` - the registry's existing `chatbot | reasoning` kinds are not extended; see design.md).
- Per turn, three steps before a final answer, each its own span under one turn:
  1. **Classify** - an HTTP call to the external, already-running context-classifier service
     (`https://github.com/vikasagarwal2485/llms/tree/main/classifier_model`'s `POST /classify`, confirmed live
     at `http://127.0.0.1:8765`). The agent discovers this service's address from its own registration at
     startup (`add-custom-model-provider-kind`'s `custom_model_endpoints`, exposed via `whoami` for a declared
     task resolving to a `custom`-kind provider) the same way it discovers its routing model group - `--classifier-url`
     is an explicit override, not the primary mechanism, mirroring `reasoning_agent.py`'s own
     `--reasoning-model-group`-style overrides. Recorded as a `tool` span, not an `llm` span - it is a local
     pre-trained text classifier, not a generative model call, and is explicitly exempt from the gateway-only
     constraint below.
  2. **Route** - a small LLM call that, given the classifier's result, decides what to do next and calls a tool
     to resolve that decision to a concrete action. This call is addressed to a *new*, agent-specific,
     gateway-routed, self-discovered task-scoped model group (e.g. `classifier-router-agent__routing`) -
     proving the self-discovery/gateway-sync/fallback mechanism (`add-agent-self-discovery`,
     `add-declared-model-fallback`, `add-classification-task-routing`) generalizes to a fourth, novel task name
     defined purely by this new agent, with no further backend changes.
  3. **Resolve route** - the routing LLM call's tool invocation reaches a new, standalone MCP server (a separate
     process) exposing one `resolve_route` tool, backed by a small, editable label -> action mapping (e.g. a
     YAML file), so the mapping can be extended with new labels or target agents without touching the graph.
- Two distinct downstream branches this phase, so the graph demonstrably branches on a real decision rather than
  having only one path:
  - **Reasoning branch**: spawns the existing `agents/reasoning_agent.py` as a subprocess for the actual
    problem-solving turn. That subprocess streams its *own*, separate turn to the platform under its own agent
    identity, fully gateway-routed exactly as already proven - the router's turn records a `tool` span for the
    hand-off and its result, not the reasoning agent's own LLM spans.
  - **Short-circuit branch** (e.g. the classifier's `spam` label): the router's turn finishes immediately with a
    canned response and makes no further LLM or sub-agent call at all.
- **Hard constraint carried through unchanged**: the router process itself never calls any LLM provider
  directly. Its only LLM call (the routing decision) goes through the shared gateway by a discovered model
  group, the same way every existing reference agent's calls do. The external classifier call is a non-LLM tool
  call and is the one step explicitly outside this constraint, because it is not a model call at all.

## Capabilities

### New Capabilities
(none - this is additional reference-agent material under the existing capability below)

### Modified Capabilities
- `reference-agents`: adds the classifier-routed multi-agent orchestrator and its routing-mapping MCP tool as
  new requirements under this existing capability, which already documents the platform's runnable example
  agents.

## Impact

- New files under `agents/`: the new agent script, a new standalone MCP routing-mapping server script, and a
  small routing-mapping config file (label -> action/agent).
- New Python dependencies in `agents/requirements.txt`: `langchain`, `langgraph`, and an MCP client/server
  library (e.g. `mcp`), scoped to the `agents/` venv only - no change to `backend/`'s dependencies.
- No backend code changes required *by this agent itself*: self-discovery, gateway-sync, and declared-model
  fallback already compute and route task-scoped model groups generically by name, which the prior
  `add-classification-task-routing` change already proved for a third task type; this change reuses that same
  generality for a fourth, agent-defined task name ("routing") with no new backend logic.
- **Depends on `add-custom-model-provider-kind`** (a separate, precursor change) being implemented first: this
  agent registers its classification dependency as a `custom`-kind model rather than a hardcoded address, and
  relies on that change's `whoami` extension to discover it. That dependency's own backend changes (a new
  provider kind, a non-chat "Test connection", a gateway-sync skip branch, a `whoami` extension) are entirely
  that change's scope, not this one's.
- Depends on the external classifier service already running at `http://127.0.0.1:8765`
  (`https://github.com/vikasagarwal2485/llms/tree/main/classifier_model`) - building, training or modifying that
  service is explicitly out of scope; this change only adds an HTTP client against its existing `/classify`
  endpoint.
- Registers a new reference agent instance in whatever platform deployment this is run against (its own
  provider/evaluator configuration, declared models, and gateway model groups), the same way `reasoning_agent.py`
  already does.
