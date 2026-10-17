# Proposal

## Why

An agent's declared model can fail for reasons that have nothing to do with the request itself -
a cloud provider outage, a rate limit, an expired/misconfigured credential (the
`AZURE_OPENAI_API_KEY` class of failure documented live in `gateway/README.md`'s "Provider
credentials" section), or a transient network error between the gateway and the provider. Today
that failure surfaces straight to the agent as an error with no configured way to keep the turn
alive on a different, working deployment - for example falling back from an Azure OpenAI model to
a local Ollama model. The gateway's own spec (`agent-llm-gateway`, "No silent deployment
substitution") already anticipates this: it carves out an explicit exception for "a fallback
deployment... explicitly configured for that group" and has an un-implemented scenario describing
it. This change implements that exception.

Research performed directly against the running gateway (this session) found the mechanism that
actually works: passing `"fallbacks": ["<group-name>"]` on the individual completion request
causes LiteLLM to retry against that group when the primary fails, and the response's
`x-litellm-model-group` header identifies which group actually answered. The alternative -
configuring a fallback gateway-wide via `POST /config/update`'s `litellm_settings.fallbacks` -
was also tested live and found unreliable: the endpoint reports success but a subsequent request
that does not itself pass `fallbacks` still fails with no fallback attempted. This proposal is
scoped to the verified-working, per-request mechanism only.

## What Changes

- A `declared_models` entry gains an optional `fallback` field: a second model reference (same
  shape as `model`) to use when the primary fails. Either reference may be local or hosted - the
  motivating case is a hosted primary falling back to a local model, but the mechanism does not
  need to special-case that; it configures and uses a second gateway group exactly like the first.
- `gateway_sync` creates a second gateway model group for a task type that declares a fallback -
  `<agent-slug>__<task_type>__fallback` - alongside the existing primary group, and removes it
  when the fallback is cleared or the declared model is removed.
- `reasoning_agent.py`'s `call_llm` passes `fallbacks=[<fallback-group-name>]` on the completion
  request when a fallback group is configured for that call's task, and the span it reports
  through the agent SDK is unchanged (it already records whichever concrete model actually
  answered, via the existing `x-litellm-model-group`/response-model resolution - see
  `_concrete_model` in the module).
- `reasoning_agent.py` gains `--reasoning-fallback-group`/`--generation-fallback-group` CLI flags
  (optional, default to none configured), following the same **temporary, explicit** pattern as
  the existing `--reasoning-model-group`/`--generation-model-group` flags (`add-gateway-model-sync`
  "Approach A") - a caller must know and pass the exact synced fallback group name until
  self-discovery (a separate, parallel proposal, `add-agent-self-discovery`) removes that manual
  step.
- Frontend: an optional "fallback model" input next to each declared-model row, in both the
  registration form and the agent settings panel, using the same `DeclaredModelPicker` and
  data-sharing-acknowledgment gating a fallback model reference already requires when it is a
  hosted model.

## Capabilities

### Modified Capabilities
- `agent-llm-gateway`: clarifies and fulfills the "No silent deployment substitution" requirement
  - a configured fallback is a caller-specified, per-request fallback model group (not a second
    deployment silently load-balanced under the same group name), matching the mechanism verified
    live against the gateway; adds a scenario documenting that gateway-wide fallback configuration
    is not a supported mechanism.
- `gateway-model-sync`: a declared model's optional `fallback` reference is synced to its own
  gateway group alongside the primary, and removed when no longer declared.
- `agent-registry`: a declared model entry may carry an optional `fallback` model reference,
  validated the same way the primary reference is, and subject to the same hosted-provider
  data-sharing acknowledgment.
- `reference-agents`: the reasoning agent's gateway calls pass a configured fallback group on the
  underlying request so a failed primary deployment does not fail the turn when a working fallback
  is configured.

## Impact

- `backend/app/schemas.py` (`DeclaredModelSpec`, `declared_model_ref` and validation helpers).
- `backend/app/core/gateway_sync.py` (`sync_agent_model_groups`, `to_litellm_params` or a sibling
  for the fallback group, `_upsert_group`/`_delete_group` reuse).
- `backend/app/repo.py` (acknowledgment check already generalized to cover any model reference in
  `declared_models` - a `fallback` reference reuses it unchanged, verified in design.md).
- `agents/reasoning_agent.py` (`call_llm`, `solve_one`, `run_once`, `run_suite`, CLI flags).
- `frontend/src/components/agents/DeclaredModelPicker.tsx`, `AgentsPage.tsx`,
  `AgentSettingsPanel.tsx`.
- `gateway/README.md` ("What's still out of scope" currently states "No `fallbacks` are configured
  on any group" - this change removes that line and documents the new mechanism).
