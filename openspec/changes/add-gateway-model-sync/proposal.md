# Proposal

## Why

`gateway/config.yaml` (from `add-litellm-gateway-infra`) is hand-authored and static: the two
model groups it defines for the reference reasoning agent exist whether or not any agent actually
declares them, and nothing keeps them in sync with the `Agent` registry's `declared_models`
(`add-agent-multi-model-registry`). This was a known, explicitly deferred gap - that change's
design.md said the registry should become authoritative and "a later change should generate or
validate the gateway's `config.yaml` against it." It has now surfaced as a real, confusing problem:
an operator can register an agent with one declared model while the gateway still has two
hand-configured groups for it (or none at all), with nothing to catch or reconcile the mismatch.

Verified directly against a running gateway (session research, 2026-10-15): LiteLLM Proxy supports
fully dynamic, database-backed model management (`STORE_MODEL_IN_DB=True` plus the `/model/new`,
`/model/update` and `/model/delete` admin endpoints) as an alternative to `config.yaml`'s static
`model_list`. A deployment created this way takes effect immediately (no restart), can carry
generation-parameter defaults (e.g. `temperature`) per deployment, and its `api_key` still accepts
the `os.environ/<VAR>` indirection - resolved and encrypted at rest by the gateway, never passed
through the backend or the wire as a literal key. This makes it possible for the `Agent` registry
to be the single source of truth for a task-routed agent's models, generation parameters, and
their presence in the gateway, instead of maintaining two disconnected configurations.

## What Changes

- `Agent.declared_models`'s value type widens from a bare model-reference string to either a
  string (unchanged shorthand) or an object carrying the model reference plus optional generation
  parameters (e.g. `{"model": "@anthropic-main/claude-sonnet-5", "params": {"temperature": 0.2}}`) -
  backward compatible with every agent registered today.
- On agent create and on any settings update that changes `declared_models`, the platform
  attempts to create/update/delete the gateway's `<agent-slug>__<task-type>` model group(s) to
  match, via the gateway's dynamic model-management API - not by hand-editing `config.yaml`.
- The gateway is run with `STORE_MODEL_IN_DB=True`; per-agent model groups are no longer expected
  to be hand-authored in `config.yaml` (which stays for genuinely shared/fixed deployments, if
  any - see design.md).
- A gateway sync failure (gateway unreachable, provider misconfigured, etc.) is surfaced to the
  caller as a non-blocking warning in the create/update response - it never blocks saving the
  agent's settings, since not every agent depends on the gateway (`chatbot.py` still doesn't).
- **BREAKING**: none at the public schema level - `declared_models` values that were plain strings
  keep working unchanged; the object form is additive.

## Capabilities

### New Capabilities
- `gateway-model-sync`: keeps the gateway's per-agent model groups consistent with what the
  `Agent` registry declares, including each declared model's generation-parameter overrides,
  without requiring the gateway's own config file to be hand-edited per agent.

### Modified Capabilities
- `agent-llm-gateway`: model groups MAY now be created, updated and removed dynamically through
  the gateway's own management API, in addition to (not instead of) static `config.yaml` entries.
- `agent-registry`: a declared model's value MAY now carry generation-parameter overrides
  alongside its model reference.

## Impact

- **Affected code**: `backend/app/models.py` (`Agent.declared_models` value shape), `backend/app/schemas.py`
  (`AgentCreate`/`AgentSettingsUpdate` validation), a new `backend/app/core/gateway_sync.py`,
  `backend/app/repo.py` (call the sync after a successful create/update), `backend/app/api/agents.py`
  (surface sync results in the response), `gateway/README.md` (`STORE_MODEL_IN_DB=True`, the
  backend's own gateway admin credential).
- **New secret**: the backend needs a gateway-side admin credential (distinct from the master key
  used interactively today) to call the management endpoints - see design.md for the recommended
  scoping.
- **Depends on**: `add-litellm-gateway-infra` (the gateway and its database),
  `add-agent-multi-model-registry` (`declared_models`). Independent of
  `add-reasoning-agent-task-routing` and `add-classification-task-routing`, though it makes both
  more robust (the groups they rely on are now guaranteed to exist and match the registry).
- **Not affected**: `AgentSpan.model`, `plan_turn_evaluators`, the judge pipeline, and the agent
  processes' own code (`reasoning_agent.py` keeps addressing the same
  `<agent-slug>__<task-type>` group names it does today; what changes is who populates what's
  behind those names).
