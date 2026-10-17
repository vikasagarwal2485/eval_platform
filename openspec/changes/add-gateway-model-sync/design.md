# Design

## Context

See `proposal.md` - Why, and the verified facts gathered directly against a running gateway
(session research, 2026-10-15): `STORE_MODEL_IN_DB=True` plus `/model/new`/`/model/update`/
`/model/delete` lets a model group be managed at runtime, takes effect immediately, accepts
generation-parameter defaults (`temperature` confirmed working) in `litellm_params`, and resolves
an `api_key: "os.environ/<VAR>"` reference server-side - the literal key is never echoed back in
any response and ends up encrypted at rest in the gateway's own database, not transmitted in the
clear at any point. Static and dynamic groups were confirmed to coexist without conflict.

Today, `Agent.declared_models` (`add-agent-multi-model-registry`) and `gateway/config.yaml`
(`add-litellm-gateway-infra`) are two independent, manually-kept-in-sync pieces of configuration.
This change makes the registry authoritative and the gateway's per-agent groups a generated
projection of it, resolving the gap that change's design.md flagged and deferred.

## Goals / Non-Goals

**Goals:**
- One place (the `Agent` registry) to declare a task's model and its generation parameters.
- The gateway's per-agent model groups reflect that declaration automatically, without hand-edited
  YAML, and take effect immediately.
- Provider credentials keep flowing only as environment-variable references, end to end.

**Non-Goals:**
- Not replacing `gateway/config.yaml` entirely - any deployment shared across agents, or not tied
  to a specific agent's declared models, can still be configured there. This change only makes
  per-agent groups no longer *need* to be.
- Not changing how an agent process addresses its own group names (`reasoning_agent.py` keeps its
  hardcoded `<agent-slug>__<task-type>` constants) - teaching an agent to discover its own group
  names from the registry at runtime is a worthwhile follow-on, not required for this change's
  core problem (the registry and the gateway disagreeing about what a group contains).
- Not building a background reconciliation job that retries failed syncs on a schedule - a failed
  sync is surfaced once, at the point it failed; retrying happens the next time the agent's
  settings are saved (including, trivially, saving them unchanged). A scheduled reconciler is a
  reasonable future enhancement if manual retry proves insufficient in practice.
- Not solving RBAC/least-privilege for the sync credential beyond what's verified below - see
  Risks.

## Decisions

**Sync is attempted after the database write commits, not inside the same transaction.** A
gateway sync failure must never roll back a valid registry write (an agent that doesn't depend on
the gateway, like `chatbot.py`, must be registerable even if the gateway is down). `repo.create_agent`/
`update_agent_settings` commit as today; the API layer (`app/api/agents.py`) calls the sync step
afterward and folds its result into the response, never into the persisted `Agent` row in this
version (see Non-Goals - no new persisted sync-status field yet; keeping state only in the
response keeps this change's schema footprint small, at the cost of not being able to show "last
sync status" later without a fresh attempt).

**Group naming stays `<agent-slug>__<task-type>`, slug derived from the agent's registered
`name`.** Matches the convention `add-litellm-gateway-infra`/`add-reasoning-agent-task-routing`
already established; no new naming scheme to learn. The slug is the agent's `name` unchanged if it
already satisfies LiteLLM's model-name constraints, else a conservative kebab-case fold - exact
rule is a task-level detail, not a design-level one, since it only has to be consistent with
itself.

**Model-reference translation is a small, explicit function, not folded into `parse_ref`.**
`declared_models`' values stay in the platform's own reference format (bare Ollama name or
`@provider/model`, validated by the existing `parse_ref()`) - this is what `same_model`/
`same_family` and the never-self-judge check already operate on, and changing that format would
ripple well beyond this change's scope. A new `to_litellm_params(ref: str, params: dict | None) ->
dict` in `backend/app/core/gateway_sync.py` does the one-way translation at sync time only:
- A bare name (`"qwen3:8b"`) → `{"model": "ollama_chat/qwen3:8b", "api_base": settings.ollama_base_url}`.
- `"@<provider-name>/<model-id>"` → look up the `Provider` row by name for its `kind`, `key_env`,
  `base_url`, `api_version`; map `kind` to LiteLLM's provider prefix (`openai`, `anthropic` match
  directly; `azure-openai` needs its own mapping - confirm the exact LiteLLM prefix as a task,
  this repo's own `CloudBackend` adapters already encode the equivalent mapping once and are the
  reference for it) → `{"model": f"{litellm_provider}/{model_id}", "api_key": f"os.environ/{key_env}", "api_base": base_url, ...}`.
- Any `params` object from `declared_models` is merged into the resulting `litellm_params` as-is
  (e.g. `temperature`) - no validation beyond what the gateway itself does; this change does not
  attempt to know every provider's valid parameter set.

**A sync result is reported, never silently swallowed, and never blocks the save.** The
create/update response gains an optional `gateway_sync` object
(`{"status": "ok" | "error" | "skipped", "detail"?: string}` per affected task type) - `"skipped"`
covers the case where no gateway admin credential is configured at all (a valid deployment choice
for an installation that doesn't use task-routed agents yet). This is the "fail visibly, never
silently" principle already established in `add-litellm-gateway-infra`/
`add-reasoning-agent-task-routing`, applied to the registry side.

**The backend holds a dedicated gateway admin credential, read from its own environment,
separate from the interactive operator's master key.** Whether LiteLLM's role system (under
`STORE_MODEL_IN_DB=True`) supports minting a key scoped to model management only, short of full
master-key rights, was not verified in this session's research and is listed as an open question
below rather than assumed. If it does, that's the recommended credential; if the version in use
doesn't support it, the master key is the fallback, with the same env-var-only, never-logged
discipline `KeyProvider` already enforces for every other credential this platform holds.

## Risks / Trade-offs

[The backend now holds a gateway admin credential, widening what a backend compromise could
reach - previously the backend held no gateway credential at all] → scope that credential as
tightly as the gateway's own role system allows (see Decisions above); document it in
`gateway/README.md` alongside the existing virtual-key guidance, with the same storage/rotation
discipline.

[A model group an agent's own code is still actively using could be updated or removed mid-flight
if the registry changes while a call is in progress] → accepted as an inherent property of making
the registry the live source of truth; LiteLLM's own in-flight-request handling (not something this
platform controls) determines whether a request started just before an update completes against
the old or new configuration. Not a new risk this change introduces - the same is already true of
any live `config.yaml` reload today.

[Translating `declared_models` into `litellm_params` duplicates, in a second place, knowledge this
repo's `CloudBackend` adapters already encode about how to reach each provider kind] → explicitly
scoped as a small, explicit function rather than a shared abstraction with `CloudBackend`, since
`CloudBackend` talks to providers directly and this talks *about* them to the gateway; forcing a
shared abstraction now would be premature given only this one caller exists. Revisit if a third
consumer of "platform ref → provider connection details" appears.

## Open Questions

- Does this LiteLLM version's role system support a model-management-only credential, or does
  syncing require full master-key rights? Resolve during implementation by testing against the
  real gateway (the same way this proposal's other facts were verified) before deciding the
  credential's final scope - this does not change the spec or the approach, only which credential
  the backend is configured to use.
- Exact LiteLLM provider-prefix mapping for `azure-openai` (`kind` in this platform) - confirm
  against `CloudBackend`'s existing Azure handling during implementation; does not change the
  approach, only one line of a lookup table.
