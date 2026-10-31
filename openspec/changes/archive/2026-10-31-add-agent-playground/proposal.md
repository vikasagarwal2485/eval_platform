# Proposal

## Why

Today, running any of the three reference agents (`chatbot.py`, `reasoning_agent.py`,
`classifier_router_agent.py`) against a real task means an operator opening a terminal, copying a
freshly-issued ingest token and a hand-minted gateway virtual key, and typing a CLI invocation by
hand - with a system prompt that's hardcoded in the script and no way to attach a skill (skills
today only attach to a benchmark run, per `skills-registry`). There is no UI path to pick a
registered agent, give it a prompt/skill/task, and watch it run. This blocks the platform's own
stated goal of making live-agent evaluation adoptable "without requiring the user to build an
agent first" (`reference-agents`) - today that still requires comfort with a terminal, manually
managed credentials, and reading each script's `--help`.

## What Changes

- A new **agent catalog** (`agents/catalog.yaml`) describes the three runnable agent flavors
  (chatbot, reasoning, classifier-router): entrypoint command, the task-scoped model-group slots
  each flavor declares, and the new flags each script gains (see below). This is a static,
  repo-shipped catalog of *flavors*, not of registered `Agent` rows.
- **BREAKING**: `Agent.kind`'s enum gains a third value, `router`, so `classifier_router_agent.py`
  registers under its own kind instead of reusing `reasoning` (which today silently borrows that
  kind's built-in rubric despite being an orchestrator, not a multi-step reasoner). Existing rows
  with `kind: "reasoning"` are unaffected; this only changes what a *new* classifier-router
  registration should use.
- A playground-eligible agent, at registration, gets two additional encrypted-at-rest credentials
  the platform did not previously retain in reversible form: a copy of its own platform ingest
  token, and a gateway virtual key the platform mints and stores on the agent's behalf (scoped to
  that agent's own synced model groups). This is a deliberate, scoped exception to the
  hash-only/shown-once convention (`agent-registry`, `Provider`/D4) - made only for agents the
  platform itself may spawn, never for the credential an operator still pastes into a terminal by
  hand for a non-playground agent.
- `chatbot.py`, `reasoning_agent.py`, and `classifier_router_agent.py` each gain three new CLI
  flags: `--system-prompt` (overrides the script's hardcoded default), `--skill` (repeatable; fetches
  a named skill's instructions from the platform and prepends them to the system prompt, the same
  content a benchmark run already attaches), and `--task` (the one-shot problem/input to answer,
  replacing the scripts' existing stdin/REPL entry point for this invocation style).
- A new backend-owned **spawn** endpoint launches a catalog flavor as a real subprocess - the
  actual script, not a reimplementation - wired with the registered agent's stored declared models,
  fallback groups, discovered self-identity, decrypted platform token and gateway virtual key, and
  the caller-supplied system prompt/skills/task. One spawn is one-shot: the process runs the one
  task, emits its turn via the existing ingest path exactly as a terminal-run instance would, and
  exits.
- A new **Agent Playground** page: pick a registered, playground-eligible agent from a catalog-backed
  list; edit its system prompt; pick zero or more skills; type the task; spawn; watch the resulting
  turn stream live in a right-hand panel (reusing the existing per-agent SSE feed), appearing in
  that agent's ordinary conversation/evaluation history identically to a terminal-run turn.

## Capabilities

### New Capabilities
- `agent-playground`: the agent-flavor catalog, playground-eligible registration (encrypted
  credential storage, spawn readiness), the backend-managed one-shot spawn of a real reference-agent
  script, and the UI to drive it end to end with a live conversation view.

### Modified Capabilities
- `agent-registry`: `kind` gains the `router` enum value for the classifier-router flavor.
- `gateway-model-sync`: gains virtual-key minting/rotation scoped to an agent's own synced model
  groups, alongside the model-group sync it already performs, so the platform can hold a working
  gateway credential for an agent without an operator hand-running `/key/generate`.
- `skills-registry`: a skill's instructions become fetchable and attachable to a single live agent
  invocation, not only to every model a benchmark run evaluates.
- `reference-agents`: each of the three scripts documents and accepts an operator/platform-supplied
  system prompt, zero or more attached skills, and a one-shot `--task` input, instead of only a
  hardcoded prompt and an interactive/stdin loop.

## Impact

- **Backend**: `app/models.py` (`Agent` gains encrypted-credential columns, `kind` enum), new spawn
  endpoint + subprocess-lifecycle module, gateway virtual-key mint/rotate wiring in
  `app/core/gateway_sync.py`, a skill-fetch endpoint usable outside a run context, a migration.
- **Agents**: `agents/catalog.yaml` (new), `agents/chatbot.py`, `agents/reasoning_agent.py`,
  `agents/classifier_router_agent.py` (each gains `--system-prompt`/`--skill`/`--task`).
- **Frontend**: new Agent Playground page/route; reuses `useAgentEvents.ts`'s existing SSE feed for
  the live-conversation panel; extends agent registration/settings UI for playground eligibility
  and credential configuration.
- **Security**: introduces the platform's first reversibly-stored secret (encryption key
  management, rotation story) - previously every credential in this codebase was either hash-only
  or an externally-held env-var reference.
