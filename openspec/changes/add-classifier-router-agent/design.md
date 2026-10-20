# Design

## Context

Both existing reference agents call `litellm.completion()` directly, pointed at the gateway with an
`openai/`-prefixed model string and `api_base`/`api_key` set to the gateway's own URL/virtual key
(`agents/reasoning_agent.py`'s `call_llm()`) - this `openai/` prefix is a quirk of using litellm's own
universal-router client function against an arbitrary `api_base`, verified while building
`add-litellm-gateway-infra`. Each agent discovers its own task-scoped gateway model group names at startup via
`GET /api/ingest/v1/whoami` (`add-agent-self-discovery`), falling back to a hardcoded default and a visible
warning if discovery fails; an explicit CLI override always wins over discovery for its own task
(`reasoning_agent.py`'s `_resolve_model_groups()`). A fallback model group is passed per-call as the request's
own `fallbacks` field - the only mechanism verified to actually work against the gateway
(`add-declared-model-fallback`). Model group names follow `<agent-slug>__<task-type>`, computed generically by
`backend/app/core/gateway_sync.py` from whatever keys an agent's `declared_models` has - proven to generalize to
a third, novel task name ("classification") with zero backend changes by `add-classification-task-routing`.

The agent SDK (`agents/eval_agent_sdk`) already supports two span kinds: `Turn.llm_call()` (`kind: "llm"`,
requires a `model`) and `Turn.tool_call()` (`kind: "tool"`, `name`/`args`/`result`, no `model` - already used
nowhere yet, but present and unused by neither existing reference agent). No SDK change is needed for this
change.

`agent-registry`'s existing spec text enumerates an agent's `kind` as exactly `chatbot` or `reasoning` - adding
a third value is a spec-level change this proposal does not make (see Decisions).

The context-classifier service (`https://github.com/vikasagarwal2485/llms/tree/main/classifier_model`,
confirmed live at `http://127.0.0.1:8765`) is a local, pre-trained multi-task text classifier (`MultiTaskClassifier.load(...)`
at startup) - it is not a generative model and makes no LLM API call of its own. Its `POST /classify` returns,
per request, a result per loaded task simultaneously (confirmed live: `tasks_loaded: 2` - `ag_news`
{Business/Sci-Tech/Sports/World} and `spam` {ham/spam}), not one single label - any routing-mapping rule set
must be able to key off more than one task's result per request, and decide precedence between them (e.g. spam
takes priority over topic).

This agent registers the classifier as a `custom`-kind model (`add-custom-model-provider-kind`, a separate
precursor change this one depends on) rather than wiring its address in only as a CLI default - `whoami`'s
`custom_model_endpoints` field (added by that change) exposes a `custom`-kind declared task's `base_url`/`model_id`
directly, so this agent discovers the classifier's address the same way it discovers its routing model group,
with no gateway group involved (there is none for it - the classifier is never routed through the gateway).

## Goals / Non-Goals

**Goals:**
- Prove the gateway-only constraint ("every real LLM call goes through the shared gateway by a discovered,
  overridable, fallback-capable task-scoped group name") holds for a LangChain/LangGraph-orchestrated agent that
  uses real LLM-driven tool-calling, not just litellm's bare `completion()` call pattern.
- Prove the task-scoped model group convention and its self-discovery/fallback mechanism generalize to a task
  name this agent invents ("routing"), not just the three the platform already documents, with no further
  backend change - continuing the same proof pattern `add-classification-task-routing` established.
- Prove a turn can hand off to a second, independently registered agent process and that hand-off is visible in
  this agent's own spans without misattributing the second agent's LLM calls to this one.
- Demonstrate a real MCP server as the mechanism resolving a classification result to a routing decision,
  pluggable without editing the orchestrator's own code.

**Non-Goals:**
- Building, training, retraining or modifying the external classifier service - it is used exactly as it
  already runs, over HTTP, as a black box.
- Adding a third `AgentKind` value to the registry - this agent registers with kind `reasoning` (closest
  existing fit: multiple internal calls per turn), avoiding any change to `agent-registry`'s spec or schema.
- Extending the Agents page's declared-model task-type dropdown (`TASK_TYPE_OPTIONS`, currently
  Reasoning/Generation/Classification/Default) with a "Routing" option - the backend already accepts any
  task-type key (`declaredModelTasks.ts`'s own comment confirms this), so this agent is registered the same way
  this project's own test/demo agents already have been this session: a direct API call, not the Agents page UI.
  Adding a fifth UI option is a reasonable future follow-up, not required for this change to be usable or
  tested.
- Modifying `reasoning_agent.py` itself - it is invoked unmodified, exactly as any operator could already invoke
  it from a shell.
- More than two downstream branches, retry/pooling for the subprocess hand-off, or persisting routing-mapping
  edits through any platform UI/API - a local, hand-edited config file for the MCP server is enough for this
  phase.

## Decisions

**1. New standalone script, not a modification of an existing agent.** `agents/classifier_router_agent.py`,
following `reasoning_agent.py`'s established CLI conventions (`--platform-url`, `--token`, `--gateway-url`,
`--gateway-key`, `--problem`) plus its own: `--classifier-url` (an **override** - unset by default, see Decision
9), `--routing-model-group`/`--routing-fallback-group` (mirroring `--reasoning-model-group` etc.), and
`--reasoning-agent-token`/`--reasoning-agent-gateway-key` (the credentials the *reasoning branch* needs to spawn
`reasoning_agent.py` as its own, separately-registered agent identity - this orchestrator's own token identifies
only the orchestrator).

**2. Single-task discovery, not a reuse of `_resolve_model_groups()`.** This agent has exactly one LLM task
("routing"), so it inlines the same three-line pattern (`explicit override or discovered.get("routing") or
hardcoded default`, with the same visible warning on discovery failure) rather than calling
`reasoning_agent.py`'s three-task-shaped helper. Same behavior, no new resolution logic, no awkward fit.

**3. LLM calls via `langchain-openai`'s `ChatOpenAI`, pointed at the gateway with `base_url`/`api_key` - no
`openai/` prefix.** The `openai/` prefix trick in `reasoning_agent.py`'s `call_llm()` is specifically a litellm
quirk (telling its universal-router `completion()` which provider an arbitrary `api_base` is), not a general
OpenAI-wire-protocol requirement. `ChatOpenAI` already only ever speaks the OpenAI wire format, so pointing it
at the gateway's own OpenAI-compatible surface is expected to need no such prefix - **this needs empirical
verification during implementation** (task 2.1), the same way the original prefix requirement itself was only
discovered by testing live against the gateway.

**4. Gateway fallback passed via `extra_body`.** The gateway's `fallbacks` field is litellm-proxy-specific, not
part of the standard OpenAI chat-completions schema; `langchain-openai`'s `ChatOpenAI` accepts arbitrary
passthrough fields via `extra_body`/`model_kwargs`. The exact field/kwarg name is version-sensitive and will be
confirmed live against the installed `langchain-openai` version during implementation (task 2.1), mirroring how
the `openai/`-prefix requirement itself was confirmed empirically rather than assumed.

**5. The routing decision is a one-round ReAct-style tool call, not an open-ended agent loop.** The routing LLM
is given the classifier's full per-task result and exactly one tool (`resolve_route`) bound via LangChain's
tool-calling API; a system prompt instructs it to call that tool before answering. The graph executes at most
one tool call, feeds the result back, and takes the model's next response as the final routing decision - kept
intentionally simple (one bounded round-trip, not a multi-step agent loop) since the actual decision logic lives
in the deterministic MCP tool, not the LLM's own reasoning.

**6. MCP server over stdio, spawned by the router as a subprocess - not a long-running network service.** A
"real MCP server" per the user's explicit choice, and MCP's own stdio transport is the common case for exactly
this shape (a client spawning a local server subprocess, as e.g. Claude Desktop does for its own local MCP
servers) - no port to manage or conflict with, no separate process for an operator to remember to start, and the
router is the MCP client that owns the server's lifecycle for the duration of its own run. *Alternative
considered*: a long-running HTTP/SSE MCP service, rejected for this phase - it adds a second always-on process
to operate for no benefit this reference material needs, and stdio is just as genuinely "a separate process
speaking the MCP protocol" as the user asked for.

**7. Routing-mapping config is an ordered rule list, first match wins, explicit `default`.** Each rule names a
classifier task, a label (or `"*"` for any label under that task), and either `short_circuit` (with a canned
response) or `handoff` (naming the target agent). No matching rule falls through to a `default` of
`{"action": "error"}` - satisfying the spec's "does not guess a target" requirement - rather than silently
picking some branch.

**8. The reasoning branch spawns `reasoning_agent.py` as a subprocess, once per turn, and waits for it
synchronously.** Per the user's explicit choice over an in-process import - keeps the two agents fully
decoupled (separate venvs/dependency sets are even possible), at the cost of per-call process-spawn overhead
and parsing its stdout for the final answer, both acceptable for this reference/exploration material.

**9. The classifier's address is self-discovered via `custom_model_endpoints`, not a hardcoded CLI default.**
Mirrors Decision 2's single-task pattern: explicit `--classifier-url` override wins if given; otherwise `whoami()`'s
`custom_model_endpoints["classification"]` (resolved by `add-custom-model-provider-kind`) supplies the base URL;
if discovery itself fails or that key is absent, falls back to the hardcoded `http://127.0.0.1:8765` default with
the same visible warning every other discovery fallback already prints. *Alternative considered*: keep
`--classifier-url`'s hardcoded default as the only mechanism (the original draft of this design) - rejected once
registering the classifier as a `custom` model was decided, since leaving its address undiscoverable would make
it the one dependency this agent treats differently from every other task-scoped one, for no reason once the
platform has somewhere to register it.

## Risks / Trade-offs

- [`ChatOpenAI` may need its own prefix or header quirk against this specific gateway, discovered only once
  implementation starts] -> budget time for this exactly as the original litellm prefix requirement was found:
  empirically, against the real running gateway, documented in the code the same way once confirmed (task 2.1).
- [Parsing a spawned CLI process's stdout for the final answer is brittle compared to a typed in-process return
  value] -> `reasoning_agent.py` already prints the final answer as its last line of stdout for `--problem` mode
  today; the router reads that exact line. If `reasoning_agent.py`'s own output format ever changes, this
  integration point breaks - acceptable for reference material, called out explicitly in the code.
- [The routing LLM might not call the tool at all, or call it more than once] -> the graph treats "tool not
  called" as a visible error for that turn (never guesses), and only ever executes the first tool call if more
  than one is requested in a single response.
- [Running an additional local MCP server process adds one more thing that must be reachable for a turn to
  succeed] -> its failure is visible (the routing step fails the turn, the same way a gateway failure already
  does for every other reference agent call) rather than silently skipped.

## Migration Plan

Purely additive within this change: new files only, no changes to existing agents or frontend code; no data
migration. `add-custom-model-provider-kind` must be implemented first (this change's classify step depends on
its `whoami` extension); that dependency's own backend changes belong entirely to it, not to this change.
Rollout here is "add the files, install the new dependencies in `agents/`'s venv, register the new agent
(including its classification dependency as a `custom`-kind model) like any other." Rollback is deleting the
new files and the agent's registration; nothing else depends on them.
