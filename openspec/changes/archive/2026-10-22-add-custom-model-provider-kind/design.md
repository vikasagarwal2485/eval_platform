# Design

## Context

`Provider.kind` is `openai | anthropic | azure-openai | ollama` (`app/models.py`); `_LITELLM_PROVIDER_PREFIX`
(`app/core/gateway_sync.py`) maps each gateway-routable kind to its LiteLLM provider prefix, and
`to_litellm_params()` raises `ValueError(f"no known LiteLLM provider prefix for provider kind '{kind}'")` for
any kind not in that map - caught by `sync_agent_model_groups()`'s caller and turned into a per-task-type
`SyncResult("error", ...)`, visible on the agent's create/update response. `provider_availability()`
(`app/providers/backend.py`) skips the key-presence check only for `kind == "ollama"`; `caps_for_kind()` already
defaults an unrecognized kind to all-`False` `BackendCaps` (no code change needed there). `GET
/api/ingest/v1/whoami` (`app/api/ingest.py`) computes `gateway_model_groups` by pure string formatting
(`model_group_name(slug, task_type)` for every key in `declared_models`) with **no provider lookup at all** -
it has no way today to know whether a declared task's model actually resolves to anything gateway-routable.
`test_provider()`/`available_models()` (`app/api/providers.py`) dispatch to a `ModelBackend` (`chat_stream()`
etc.) via `_backend()` - a protocol a `custom` provider cannot implement, since it has no chat-completions
surface at all. The frontend's provider-kind option list lives in `ProviderForm.tsx`'s `<select>`, and
`KIND_LABEL` (`lib/providers.ts`) supplies its display label.

## Goals / Non-Goals

**Goals:**
- Let a provider be registered for a service that is reachable over HTTP but is not chat-completions-shaped,
  without misusing an existing kind or crashing gateway sync.
- Let an agent discover such a provider's address for one of its own declared tasks the same way it already
  discovers a gateway group name for a chat-shaped one.
- Keep every existing kind's behavior (including `ollama`, already shipped) completely unchanged.

**Non-Goals:**
- Giving a `custom` provider any way to actually serve a chat completion, a run, or a judge - `caps_for_kind()`
  already returns all-`False` capabilities for an unrecognized kind, and nothing in this change adds a `chat()`
  implementation for `custom`. It is reachable only via its own `base_url`, by whatever calls that out (an
  agent, not the platform's own runner/judging pipeline).
- Auto-discovering a custom provider's models - added by typing an id by hand, like `azure-openai` deployments.
  A custom service's own listing endpoint (if any) has no generic shape the platform could assume.
- Backfilling `model-providers`' Purpose/overview text or its other pre-existing drift from the already-shipped
  `ollama` kind (e.g. requirement 4's "unavailable for selection" wording doesn't precisely describe `ollama`'s
  real exemption either) - out of scope; this change only touches the requirements it needs to.
- Exposing `custom`-kind models through `/api/models` (the Run Evaluation setup picker) or any
  reasoning/generation/classification declared-model picker - they cannot serve any of those roles.

## Decisions

**1. `Provider` gains `kind == "custom"` and a nullable `health_check_path` column** (no default stored; `/health`
is applied at use-time when unset, the same pattern `settings.ollama_base_url` already uses as a usage-time
default rather than a stored one). `key_env` stays nullable and unused for this kind, exactly as it already is
for `ollama`.

**2. `provider_availability()`'s key-presence check is extended from `kind != "ollama"` to `kind not in
("ollama", "custom")`.** The narrowest possible change - one guard condition - rather than inventing a new
"kinds with no key" set/flag for a two-member case.

**3. `gateway_sync` gets an explicit custom-kind branch, checked before the existing prefix lookup.**
`to_litellm_params()` (or its caller) checks the resolved provider's kind first: a `custom`-kind reference
short-circuits to a distinct, named outcome ("not gateway-routed") instead of falling into the
prefix-lookup-then-raise path every other unrecognized kind still correctly takes. `sync_agent_model_groups()`
reports that outcome under the task type's key exactly where it already reports `"ok"`/`"error"`/`"skipped"`
today - no new response shape, just a new status string, so no caller (including the frontend, which already
displays whatever string the sync result carries) needs special-casing to merely show it.

**4. `whoami` resolves each declared task's provider kind before building its response, rather than remaining a
pure string formatter.** For a `custom`-kind resolution, the task's key is omitted from `gateway_model_groups`
and instead added to a new `custom_model_endpoints` object: `{"<task>": {"base_url": "...", "model_id":
"..."}}`. This is the one real logic change in this proposal - every other decision here is a narrow,
additive branch; this one teaches a previously provider-agnostic endpoint to look a provider up. Scoped
tightly: only for a reference that `parse_ref()` already recognizes as a cloud ref (`@provider/model`) and whose
provider is kind `custom` - every existing kind's resolution (gateway group name, pure string formatting) is
completely unchanged, verified by keeping the existing self-discovery tests passing unmodified.

**5. `test_provider()` branches on `kind == "custom"` before reaching `_backend()`.** A plain `httpx` GET to
`base_url + (health_check_path or "/health")`: 2xx -> `"working"`, a connection/timeout error -> `"unreachable"`,
anything else -> a generic `"error"` outcome carrying the response's status - never attempting the
`ModelBackend` protocol a custom provider cannot implement. `available_models()` (model auto-discovery) simply
never offers the fetch action for `custom`, mirroring exactly how `azure-openai` already has none (same
`409`/`not_supported` response shape, different explanatory message).

**6. Frontend: `custom` added to `ProviderForm.tsx`'s kind `<select>` and `KIND_LABEL`, with the key-env field
hidden (same `isOllama`-style boolean guard, `isCustom`) and an optional health-check-path field shown only for
it.** `ProviderCard.tsx`'s "no key needed" badge condition is extended from `isOllama` to `isOllama || isCustom`.

**7. `repo._check_provider_acks()`'s `ollama`-kind exemption is extended to `custom`.** Found while
implementing task 6.1: this gate (registering/saving an agent whose evaluator or declared model - primary or
fallback - references an enterprise provider requires a recorded data-sharing acknowledgment) currently
exempts only `ollama` ("nothing leaves the machine"). A `custom`-kind reference needs the same exemption, for
a related but distinct reason: the platform itself never sends this agent's data to a `custom`-kind provider at
all - unlike a real enterprise provider, which the platform calls *on the agent's behalf* (as a judge, or when
evaluating). A `custom` provider is only ever called directly by the agent's own code, which the platform has
no part in and nothing to acknowledge for.

## Risks / Trade-offs

- [Teaching `whoami` to resolve providers is a behavior change to a previously pure, provider-agnostic function]
  -> scoped to exactly one new branch (cloud ref resolving to a `custom`-kind provider); every other path through
  the function is provably unchanged (existing tests for the other three task-resolution shapes keep passing
  unmodified).
- [A `custom` provider's base URL is local/internal in the reference case (`http://127.0.0.1:8765`), but nothing
  stops registering one that points anywhere] -> no different from any other provider's `base_url` already
  being operator-supplied and trusted; this change does not add a new trust boundary, it reuses the existing one.
- [An operator could mistakenly register a genuinely chat-capable service as `custom`, discovering only later
  that it is never offered anywhere a chat model is expected] -> the Models page's "no key needed" badge and
  this change's explicit exclusion from `/api/models` make a `custom` provider visually and behaviorally
  distinct from every other kind, not a silent trap.

## Migration Plan

Additive only: a new `Provider.kind` value and one new nullable column (`health_check_path`) - no change to any
existing row, no backfill. Rollout is deploy-and-use; rollback is simply not registering any `custom`-kind
provider (existing kinds are completely unaffected by every decision above).
