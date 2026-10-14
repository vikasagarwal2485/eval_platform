# Design

## Context

See `proposal.md` - Why for motivation. The relevant current state:

- `ModelRouter.backend_for()` caches one `ModelBackend` per `(kind, name, key_env, base_url)` and dispatches to a factory keyed purely by `kind` (`app/providers/backend.py`); `CLOUD_CAPS` and the frontend's `KIND_LABEL`/`KIND_DEFAULTS` are likewise keyed by `kind`. Adding a provider type is already meant to be "add a kind, a factory, a caps entry, a UI label" - no other call site branches on provider identity.
- `CloudBackend` (`app/providers/cloud.py`) owns retry/backoff, SSE parsing, and redaction, all provider-agnostic. `OpenAIBackend` (`app/providers/openai.py`) builds the official OpenAI request/response shape on top of it: `Authorization: Bearer`, `POST {base}/v1/chat/completions` with `model` in the body, `GET {base}/v1/models` for discovery and `ping()`.
- `Provider` and `RegisteredModel` (`app/models.py`) hold exactly the fields the current two kinds need; neither has a slot for an Azure API version or a per-model reasoning-effort level.
- Tests exercise the real HTTP shape via `tests/fake_providers.py` (`FakeOpenAI`, `FakeAnthropic` - real Starlette/uvicorn servers), not mocks, plus an opt-in live-API smoke test (`tests/test_live_smoke_enterprise.py`) that only runs when a real key env var is set.

## Goals / Non-Goals

**Goals:**
- Azure OpenAI deployments work for generation, judging, and Test Connection through the existing runner/scoring/metrics/redaction/circuit-breaker pipeline, unchanged.
- The Ollama-shaped-chunk abstraction holds: `AzureOpenAIBackend` looks like any other `ModelBackend` to everything above it.
- `reasoning_effort` becomes a real, generic parameter (not wired specially for Azure), since it's needed for the user's actual deployment to behave correctly, not just to pass Test Connection.

**Non-Goals:**
- No Azure Resource Manager / Azure AD integration. Deployment discovery, auto-listing, and anything needing a management-plane credential stay out of scope (see proposal's "Discover a provider's models" change).
- No generic "configurable header/path template" mechanism for arbitrary gateways. Azure gets a dedicated kind because its contract is specific and well-known, not a knob that invites every future gateway to be half-supported.
- No Azure API surface beyond Chat Completions (no Assistants API, no embeddings) - matches the existing OpenAI/Anthropic scope.

## Decisions

### D1. `azure-openai` is a new, distinct `kind`; `AzureOpenAIBackend` subclasses `OpenAIBackend`
The chat-completions SSE payload shape (`choices[].delta`, `usage`, etc.) is identical between OpenAI and Azure OpenAI - only the transport differs (auth header, URL, a mandatory query parameter). `AzureOpenAIBackend(OpenAIBackend)` overrides `auth_headers()`, the request path, and `ping()`, and inherits `chat_stream()`'s SSE parsing and `build_body()`'s parameter mapping untouched.

*Alternative considered:* detect an Azure-shaped `base_url` under `kind: "openai"`. Rejected - fragile against custom domains, private endpoints, or a reverse proxy in front of the resource, and it conflates two different credential/URL contracts under one kind, which is exactly the ambiguity that produced the original bug (a key silently sent to the wrong host).

### D2. `api_version` is a required, provider-level field for `azure-openai`
`ProviderConfig` gains `api_version: str | None`; `Provider` gains a nullable `api_version` column (null for `openai`/`anthropic`). Required-ness is enforced only at the Pydantic layer, via a `model_validator(mode="after")` on `ProviderIn` that checks `base_url` and `api_version` are both present when `kind == "azure-openai"` - a cross-field check the existing per-field validators can't express. `ProviderUpdate` gets a matching optional `api_version` field.

*Alternative considered:* a generic `extra_params: dict` JSON column for provider-specific config, to accommodate not-yet-known future providers. Rejected as premature generalization for one well-understood field; a typed column is simpler to validate, migrate, and display.

### D3. The deployment-scoped path is built per call, not at adapter construction
One `AzureOpenAIBackend` instance is cached per provider (`ModelRouter._backends`) and serves every deployment registered under it; the deployment name is only known per `chat_stream()` call (the `model` argument). `AzureOpenAIBackend` builds `/openai/deployments/{deployment}/chat/completions?api-version={api_version}` inside `chat_stream()` itself and passes it to the inherited `open_stream()`. `CloudBackend.url()`'s existing `/v1`-dedup logic is a no-op for this path shape (it doesn't start with `/v1`), so it needs no change.

### D4. `auth_headers()` returns `{"api-key": key}`
No other header differences from the OpenAI adapter.

### D5. `max_completion_tokens` vs `max_tokens` also considers the `reasoning` flag, not just `official`
Today `OpenAIBackend.build_body()` picks the parameter name from `self.official` (`base_url is None`, i.e. "is this the real OpenAI endpoint") alone: official always gets `max_completion_tokens` (OpenAI's official API now accepts it universally, not only for reasoning models - confirmed by the existing test asserting this for a non-reasoning call), any custom `base_url` always gets `max_tokens`. Azure's `base_url` is always set, so a reasoning deployment like the user's `o3-mini` was always getting `max_tokens` - the wrong name - relying entirely on the existing `_adjust_for_rejection` retry (renames the parameter on a 400 and retries) to recover, at the cost of a guaranteed wasted round-trip on every single reasoning-model request. The fix is `official or reasoning`: official-endpoint behavior is unchanged (still always `max_completion_tokens`), and any custom `base_url` now also gets `max_completion_tokens` when the model is flagged reasoning, `max_tokens` otherwise exactly as before for non-reasoning models. This is a shared, additive condition in `OpenAIBackend.build_body()` - not an Azure-only branch - and keeps the rename-on-rejection path as a safety net for any combination that still disagrees.

*Alternative considered:* key the choice purely off `reasoning`, dropping `official`. Rejected during implementation - it breaks the existing, verified behavior that the official endpoint always wants `max_completion_tokens` even for non-reasoning models.

### D6. `reasoning_effort` is a per-model, optional free-text field
Added to `RegisteredModel` (nullable string), surfaced only when `reasoning=True`. Threaded through the same path the existing `reasoning` boolean already takes: `ModelRouter._resolve_cloud()` reads it alongside `model.reasoning` → `ModelRouter.chat_stream()` passes it through → `ModelBackend.chat_stream(..., reasoning_effort: str | None = None)` → `OpenAIBackend.build_body()` adds `"reasoning_effort"` to the body when both `reasoning` and a configured value are present, recording it in `params_applied`. Applies identically to `openai` and `azure-openai` - not Azure-specific code. `reasoning_effort` is added to the existing `DROPPABLE` set so a deployment that rejects it degrades the same gracefully-adjusted way as `temperature`/`seed`/`top_p`, rather than failing the whole result.

Stored as free text (not a validated enum): OpenAI's accepted values for this parameter have changed across model generations and may not match Azure's exactly for a given deployment; a provider's own 400 for an invalid value already surfaces through the existing redacted-error path, so client-side enum validation would only risk rejecting a legitimate future value.

*Alternative considered:* a per-run setting in Run setup, like the existing `think` boolean. Rejected for this change - the existing `reasoning` flag this builds on is already a per-model registration setting, not per-run, so this follows the same shape; a per-run override can be layered on later without changing it.

### D7. `CLOUD_CAPS["azure-openai"]` mirrors `CLOUD_CAPS["openai"]`
`warmup=False, unload=False, footprint=False, seed=True, context_size=False` - same kind of hosted HTTP API, same absence of a local load phase.

### D8. Test Connection for `azure-openai` requires a registered deployment, and calls it directly
`CloudBackend.ping()` defaults to `list_models()`, which Azure has no equivalent of. `AzureOpenAIBackend` overrides `ping()` to send a minimal chat completion to the first enabled deployment. `test_provider()` (`app/api/providers.py`) checks for at least one enabled `RegisteredModel` before calling `ping()` for this kind, returning a new outcome (`no_deployments`) instead of attempting a call when none exists - a real, spec'd divergence from the provider-wide ping used for `openai`/`anthropic`, and a new dependency for that endpoint (it now needs the provider's models, not just the provider row).

### D9. "Discover a provider's models" returns a clear unsupported response for `azure-openai`
`GET /api/providers/{id}/available-models` returns a 409 with an explanatory message for this kind (same status pattern already used for `key_not_set`), rather than calling a `list_models()` that doesn't exist for Azure. The frontend hides the "Fetch models" action entirely for `azure-openai` providers instead of showing a button that always errors.

### D10. A `FakeAzureOpenAI` test double, modeled on `FakeOpenAI`
Added to `tests/fake_providers.py`: routes match `/openai/deployments/{deployment}/chat/completions`, requires an `api-version` query parameter (400 if missing, mirroring real Azure behavior), and checks the `api-key` header instead of `Authorization: Bearer`. Reuses `FakeOpenAI`'s streaming/response-building logic where the shape is identical.

## Risks / Trade-offs

- **Azure's exact behavior is partly inferred** from OpenAI parity and the user's one working curl, not verified against a live resource in this environment (error shapes, which deployments support `response_format: json_schema` strict mode for judging, etc.). -> Mitigation: the same opt-in, real-API pattern already used for OpenAI/Anthropic (`test_live_smoke_enterprise.py`) gets an Azure case, so this gets verified against the user's real resource at implementation time; the existing per-parameter rejection-and-retry fallback (D5/D6) is the safety net for anything that still differs.
- **A wrong or expired `api_version` is a likely real-world failure mode** (Azure retires preview versions periodically) and today would only surface as a generic `unreachable`/`error` outcome. -> No dedicated mitigation planned beyond the existing redacted-error pass-through (Azure's own 400 for a bad api-version is already descriptive); not expanding scope to version-specific guidance or a maintained list of valid versions.
- **D5 changes default behavior for official OpenAI reasoning models too**, not just Azure. -> The observable end state is unchanged for existing OpenAI users (the rejection-retry path already got them to the same place), just one fewer round trip; covered by a new adapter unit test asserting the parameter choice directly, plus the existing retry-path tests.

## Migration Plan

- One Alembic migration (`0005_azure_openai_provider.py`): add `Provider.api_version` (nullable `String`) and `RegisteredModel.reasoning_effort` (nullable `String`). Both nullable, so existing `openai`/`anthropic` provider and model rows need no backfill and are otherwise untouched.
- Rollback: downgrade drops both columns; nothing else depends on them.

## Open Questions

- Whether Azure's structured-output (`response_format: json_schema`, strict mode) judge path - reused unchanged from `OpenAIBackend` - actually matches Azure's behavior on the user's specific api-version/deployment combination. Safely deferred: the existing rejection-and-adjust mechanism already handles a model/provider that rejects a request shape, and the Azure live-smoke test will exercise this against the user's real deployment during implementation.
- The exact accepted values for `reasoning_effort` differ across OpenAI's o-series models and may differ again on Azure. Safely deferred by storing it as free text (D6) rather than a validated enum; a provider's own rejection already surfaces through the existing error path.

## Implementation Notes

Decisions settled while implementing; behaviour in `specs/` is unchanged.

- **D5's condition is `official or reasoning`, not `reasoning` alone**, discovered from an existing test
  (`test_official_endpoint_uses_max_completion_tokens`) that already asserted the official OpenAI endpoint sends
  `max_completion_tokens` for a *non*-reasoning model too. Keying the choice purely off `reasoning` would have
  silently broken that verified behaviour; `official or reasoning` preserves it exactly while still fixing the
  Azure/gateway-plus-reasoning-model case the change set out to fix. `design.md`'s D5 text was corrected to match
  before writing the code, rather than after.
- **`AzureOpenAIBackend` overrides a single `_chat_path(model)` hook on `OpenAIBackend`**, added for this purpose,
  rather than overriding `chat_stream()` wholesale - the retry loop, SSE parsing and `final_chunk` construction are
  all inherited unchanged. `ping(model=...)` and the `ModelBackend` protocol's `ping()` both gained an optional
  `model` parameter (ignored by `openai`/`anthropic`) for the same reason: the per-deployment test connection (D8)
  needed a way to name which deployment to call without a parallel method.
- **`backend_for()`'s cache key gained `api_version`** alongside the existing `(kind, name, key_env, base_url)`
  tuple, so changing a provider's API version rebuilds its cached backend instead of leaving a stale one in place -
  the same reasoning the existing keys were already there for.
- **Clearing a required Azure field is rejected at the API layer, not the ORM layer.** `repo.update_provider()`
  accepts `clear_base_url`/`clear_api_version` unconditionally (it has no opinion on what a given kind requires);
  `update_provider()` in `app/api/providers.py` checks the provider's *current* kind before calling it and returns
  422 if the update would blank a field `azure-openai` requires. This mirrors how `ProviderIn`'s cross-field
  `model_validator` already enforces the same rule at registration time.
- **`reasoning_effort` is a free-text field on `RegisteredModel`**, edited inline in the models table via a
  blur-commit text input (`ReasoningEffortCell`) rather than mutating on every keystroke, consistent with how the
  existing reasoning/enabled checkboxes already mutate immediately but are discrete toggles rather than free text.
- **The fake Azure OpenAI server (`FakeAzureOpenAI`) subclasses `FakeOpenAI`**, reusing its response-streaming logic
  via a shared `_stream_chat_response(rec)` method (split out of `FakeOpenAI.chat()` for this purpose) and overriding
  only `_authed()`, the route path, and an added `api-version` query-parameter check - the wire payload shape needed
  no changes at all.
- **The secret-leak scan needed a second sentinel shape.** The existing `SENTINEL` is `sk-proj-...`-shaped and would
  have been caught by `Redactor`'s generic `sk-...` pattern even if the exact/partial secret-match logic were
  broken. A second, hex-only `AZURE_SENTINEL` (no recognizable prefix) was added specifically to exercise the
  exact/partial-match path in isolation, since that is the path a real Azure key actually depends on.

- **Test Connection's ping needed a reasoning-aware token budget, found via a real Azure test.** The original ping
  requested 1 output token regardless of the deployment's `reasoning` flag. For an ordinary chat deployment that's
  fine; for a reasoning deployment (e.g. `o3-mini`), the model spends part of that budget on hidden reasoning before
  producing any visible output, so a 1-token budget fails with Azure's own "max output limit reached" error before
  the model can answer at all - indistinguishable, from the UI, from a real connection problem. `test_provider()` now
  looks up the tested deployment's `reasoning` flag (not just its id) and passes it to `ping()`; `AzureOpenAIBackend.ping()`
  uses a larger budget (64) when it is set, and still passes `reasoning` into the chat request itself so the correct
  `max_completion_tokens` parameter name is used from the first attempt. This only changes the ping; a real run's
  own configured token budget is unaffected.
