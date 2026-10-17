# Proposal

## Why

Reference agents call exactly one hardcoded Ollama endpoint today (`agents/chatbot.py`,
`agents/reasoning_agent.py`), so an agent that needs different models for different sub-tasks
(for example a reasoning step and a generation step) has nowhere to express that: there is one
`--model`/`--ollama-url` pair per agent process, full stop. Standing up a shared LiteLLM Proxy
gateway, with one Router model group per `(agent, task type)`, gives agents a single place to
reach any provider by a routing name instead of a hardcoded endpoint - the prerequisite for
task-aware routing (`add-reasoning-agent-task-routing`) and for an agent registering more than
one model (`add-agent-multi-model-registry`). This change stands up only the gateway itself; no
agent or platform code calls it yet.

## What Changes

- Add a `litellm[proxy]` deployment (local/dev: a `make`-able process; documented as a supervised
  service, not an ad hoc background process) alongside the existing `backend`/`agents` setup.
- Add a `gateway/config.yaml` defining one Router model group per `(agent, task type)` for the
  first adopter (`reasoning-agent__reasoning`, `reasoning-agent__generation`), each pointing at a
  real provider deployment via `os.environ/<VAR>`-sourced keys - never a literal key in the file.
- Issue one LiteLLM virtual key for the reasoning agent process, scoped to its own model groups
  only.
- Document the gateway's health check and startup/shutdown procedure in `agents/README.md`
  (or a new `gateway/README.md`), including what a task-routed agent should do when the gateway
  is unreachable (fail the call, do not fall back to a direct provider call - see design.md).
- No agent or platform code changes - this change is infrastructure-only. Nothing calls the
  gateway until `add-reasoning-agent-task-routing` lands.

## Capabilities

### New Capabilities
- `agent-llm-gateway`: a shared, supervised LiteLLM Proxy that exposes one Router model group per
  `(agent, task type)`, holds provider keys itself (agents hold only a proxy-issued virtual key),
  and is the only place a task-routed agent process is allowed to reach a cloud or local model.

### Modified Capabilities
(none - this change adds the gateway capability only; no existing capability's requirements
change until an agent or the registry actually depends on it)

## Impact

- **New**: `gateway/config.yaml`, a deployment/run procedure for the LiteLLM Proxy, one virtual
  key.
- **Affected code**: none in `backend/` or `agents/` yet.
- **Dependencies**: adds `litellm[proxy]` as an operational dependency (not a Python package
  dependency of `backend/` or `agents/` - it runs as its own process).
- **Secrets**: provider keys (e.g. `ANTHROPIC_API_KEY`) move from "not yet needed by any agent
  process" to "held by the gateway process's environment"; a new secret class (the virtual key)
  is introduced and must be handled with the same discipline as the platform's existing
  `KeyProvider`/`Redactor` convention (env vars only, never logged or exported) even though the
  gateway is a separate process from `backend/`.
