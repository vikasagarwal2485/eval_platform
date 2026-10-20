# Proposal

## Why

Every provider kind the platform knows today (`openai`, `anthropic`, `azure-openai`, and the already-shipped
`ollama`) is chat-completions-shaped: the gateway can translate a declared model into a real LiteLLM deployment
(`to_litellm_params`), and "Test connection" pings it with a chat call. `add-classifier-router-agent` needs to
register a dependency that is not a chat model at all - an external, already-running, non-LLM classification
service reachable only over its own plain HTTP API - as a registered, self-discoverable model, the same way
every other agent dependency is registered, rather than wiring its address in by a hardcoded CLI flag no other
part of the platform knows about. Nothing in the registry or gateway-sync path today has anywhere to put a
provider that isn't chat-shaped: declaring one under an existing kind would either misrepresent it or fail
outright (`to_litellm_params` already raises `"no known LiteLLM provider prefix for provider kind '<kind>'"`
for any kind it doesn't recognize, and a key-presence check would wrongly demand a key that doesn't apply).

## What Changes

- New `Provider.kind == "custom"`: no API key concept (like `ollama`), a required `base_url`, and an optional
  health-check path (default `/health`) used only for "Test connection" - never a chat-completion request,
  since a custom provider does not implement the chat backend protocol at all.
- Models under a `custom` provider are added by typing an id by hand (no auto-discovery, like `azure-openai`
  deployments) - the id is just an identifier for whatever this custom model represents; the platform does not
  interpret it.
- **Gateway sync never attempts to create a gateway deployment for a `custom`-kind declared model.** Today,
  `to_litellm_params` raises for any kind it doesn't have a LiteLLM provider prefix for, and that raise
  surfaces as a sync *error* on the agent - exactly what happened before `ollama` was added to that map. A
  `custom`-kind reference must instead resolve to an explicit "not gateway-routed" status, reported the same way
  a sync result is reported today, never as an error.
- **Self-discovery (`GET /api/ingest/v1/whoami`) is extended**: for a declared task whose model resolves to a
  `custom`-kind provider, the response exposes that provider's `base_url` (and the model's id) directly, instead
  of a gateway group name - there is no gateway group for it. An agent that depends on a custom model can
  therefore discover its address from its own registration at startup, the same way it already discovers
  gateway group names for its gateway-routed tasks, rather than requiring a hardcoded/operator-configured
  address with nothing on the platform to keep it in sync.
- **Models page (frontend)**: the "Add a model" (provider) form offers `custom` as a kind, with no key-env
  field (base_url + optional health-check path only, mirroring how `ollama` already drops the key field), and
  the provider list labels it accordingly.
- **Out of scope / explicitly excluded**: a `custom`-kind model is never included in the unified `/api/models`
  list the Run Evaluation setup picker and an agent's reasoning/generation/classification declared-model picker
  use - it cannot serve any of those roles (it is not a chat model), so it must not be selectable where a chat
  model is expected. It is visible only on the Models/Providers page, and as a plain reference an operator can
  type into a declared-model field that the registry already accepts as free text today.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `model-providers`: adds the `custom` provider kind (registration, no key, health-check-based "Test
  connection", Models page support) alongside the kinds it already documents (this delta also brings the main
  spec's kind enumeration up to date with the already-shipped `ollama` kind, which predates this capability's
  last update).
- `gateway-model-sync`: a declared model resolving to a `custom`-kind provider is explicitly never synced to a
  gateway deployment, reported with its own clear status rather than today's generic unknown-kind error.
- `agent-registry`: self-discovery (`whoami`) exposes a custom provider's connection info directly for a
  declared task that resolves to one, instead of a gateway group name that would never actually exist for it.

## Impact

- Backend: `Provider` gains `kind == "custom"` plus an optional health-check-path column; `provider_availability`
  and the key-presence check in `available-models`/`test` gain a `custom` branch (no key concept, like
  `ollama`); `gateway_sync.to_litellm_params`/`sync_agent_model_groups` gain an explicit custom-kind branch
  (skip with a status, not raise); `GET /api/ingest/v1/whoami`'s handler gains a per-declared-task provider-kind
  lookup it does not do today (currently pure string formatting, with zero provider awareness).
- Frontend: the Models/Providers page's provider-kind options, add-provider form, and provider card gain
  `custom` support (no key-env field, an optional health-check-path field).
- No change to `model-discovery` or the Run Evaluation setup's model picker - a `custom`-kind model is
  deliberately invisible there (see What Changes).
- This is a precursor, generically-useful platform capability, not specific to any one agent. The separately
  drafted `add-classifier-router-agent` change depends on it to register its external context-classifier
  service as a `custom`-kind model instead of a hardcoded `--classifier-url` default.
