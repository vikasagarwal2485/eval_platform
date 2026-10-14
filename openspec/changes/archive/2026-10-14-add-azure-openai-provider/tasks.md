# Tasks

## 1. Data model and migration

- [x] 1.1 Add `Provider.api_version` (nullable `String`) and `RegisteredModel.reasoning_effort` (nullable `String`) columns in `app/models.py`, and an Alembic migration `0005_azure_openai_provider.py` (upgrade adds both columns; downgrade drops them). Verify `alembic upgrade head` then `alembic downgrade -1` both succeed against a fresh database.
- [x] 1.2 Extend `ProviderConfig` (`app/providers/backend.py`) with `api_version: str | None`, threaded from `ModelRouter._resolve_cloud()`'s read of the `Provider` row. Verify existing provider/router tests still pass unchanged (`api_version` is `None` for `openai`/`anthropic`).

## 2. Backend adapter

- [x] 2.1 Add `CLOUD_CAPS["azure-openai"]` mirroring `CLOUD_CAPS["openai"]` (`warmup=False, unload=False, footprint=False, seed=True, context_size=False`). Verify `caps_for_kind("azure-openai")` returns it via a unit test.
- [x] 2.2 Implement `AzureOpenAIBackend(OpenAIBackend)` in `app/providers/azure_openai.py`: `auth_headers()` returns `{"api-key": key}`; `chat_stream()` builds `/openai/deployments/{deployment}/chat/completions?api-version={api_version}` and delegates to the inherited SSE parsing and `build_body()`; `ping()` sends a minimal chat completion to a given deployment instead of `list_models()`. Verify with unit tests asserting the exact header, path, and query string built for a sample call (no network).
- [x] 2.3 Register `"azure-openai"` in `make_factories()` (`app/providers/factories.py`). Verify a provider of this kind resolves to an `AzureOpenAIBackend` instance through `ModelRouter.backend_for()`.
- [x] 2.4 Change `OpenAIBackend.build_body()`'s `max_completion_tokens`/`max_tokens` choice to key off the model's `reasoning` flag instead of `self.official` (design D5). Verify with unit tests: a reasoning-flagged model on the official endpoint sends `max_completion_tokens`; a non-reasoning model sends `max_tokens` on both the official endpoint and a custom `base_url`; existing rejection-and-rename retry behavior is unchanged.
- [x] 2.5 Add `reasoning_effort` support (design D6): a field on `RegisteredModel` read by `ModelRouter._resolve_cloud()` alongside `reasoning`, passed through `ModelRouter.chat_stream()` and the `ModelBackend.chat_stream()` protocol signature (default `None`, ignored by `AnthropicBackend`) to `OpenAIBackend.build_body()`, which includes it in the body only when `reasoning=True` and a value is set, records it in `params_applied`, and adds `"reasoning_effort"` to `DROPPABLE` so a rejecting deployment degrades gracefully instead of failing the result. Verify with unit tests covering: value included for a flagged+configured model, omitted for an unflagged model, dropped-and-retried on a simulated 400 rejection, and that the runner/judge need no changes since the router resolves and passes it internally.

## 3. Provider API and validation

- [x] 3.1 Extend `ProviderIn.kind` to `Literal["openai", "anthropic", "azure-openai"]`, add an `api_version: str | None` field, and add a `model_validator(mode="after")` requiring both `base_url` and `api_version` when `kind == "azure-openai"`; add the matching optional `api_version` to `ProviderUpdate`. Verify with API tests: registering `azure-openai` without `base_url` or without `api_version` is rejected with a field-identifying validation error; registering with both succeeds.
- [x] 3.2 Add an optional `reasoning_effort: str | None` field to `ModelIn`/`ModelUpdate`. Verify with an API test that setting it on a model persists and round-trips through `GET`.
- [x] 3.3 Include `api_version` in provider serialization and `reasoning_effort` in model serialization (neither can ever hold a key value). Verify the existing secret-leak scan still passes with these fields present.
- [x] 3.4 Implement the Test Connection precondition for `azure-openai` (design D8) in `test_provider()`: return a `no_deployments` outcome (naming that one must be registered first) when the provider has no enabled registered model, without attempting a call; otherwise call `ping()` against the first enabled deployment. Verify with API tests for both branches, the second against a fake Azure server.
- [x] 3.5 Implement the "not supported" response for `available_models()` on an `azure-openai` provider (design D9): a 409 with an explanatory message, matching the existing `key_not_set` pattern, instead of attempting `list_models()`. Verify with an API test.

## 4. Frontend

- [x] 4.1 Add an `"azure-openai"` entry to `KIND_LABEL` and `KIND_DEFAULTS` in `frontend/src/lib/providers.ts` (name/env left blank for the user to fill in - no sensible shared default). Verify with a unit test for the updated lib exports.
- [x] 4.2 Update `ProviderForm.tsx`: add Azure OpenAI to the kind selector; require Base URL and show a new required "API version" field when the selected kind is `azure-openai`. Verify with a frontend test that submitting without either shows a validation error and blocks submission.
- [x] 4.3 Update `ProviderCard.tsx`: label the model field "Deployment name" instead of "Model id" for `azure-openai` providers; hide the "Fetch models" action for this kind and show the "not available - add by name" explanation instead; render the `no_deployments` Test Connection outcome distinctly in `STATUS_LABEL`. Verify with frontend tests for each of the three states.
- [x] 4.4 Add a reasoning-effort input to the model add/edit form, shown only when "mark as reasoning model" is checked. Verify with a frontend test that it is hidden/shown correctly and its value round-trips through the mutation.

## 5. Tests: fakes and end-to-end

- [x] 5.1 Add `FakeAzureOpenAI` to `tests/fake_providers.py` (design D10): routes matching `/openai/deployments/{deployment}/chat/completions`, a required `api-version` query parameter (400 if missing), and `api-key` header authentication, reusing `FakeOpenAI`'s response-building where the shape is identical. Verify it starts and serves a scripted response via a small sanity test.
- [x] 5.2 Add end-to-end tests (new `tests/test_e2e_azure_openai.py`) against `FakeAzureOpenAI` covering: registering a provider with and without the required fields, adding a deployment, a generation run against it, Test Connection in both the no-deployment and has-a-deployment states, the fetch-not-supported response, and a run against a reasoning-flagged deployment with `reasoning_effort` set (asserting it appears in the captured request body).
- [x] 5.3 Extend `tests/test_secret_leaks.py` to run its scenarios against an `azure-openai` provider with an Azure-shaped sentinel key (no `sk-` prefix, exercising the exact/partial secret-match redaction path rather than the generic `sk-...` patterns). Verify the key is still fully redacted from the database, every API response, exports, and logs.
- [x] 5.4 Add an `azure-openai` case to `tests/test_live_smoke_enterprise.py`, gated on real `AZURE_OPENAI_API_KEY` / endpoint / api-version / deployment environment variables being set, skipped by default exactly like the existing OpenAI and Anthropic live cases.

## 6. Docs and final verification

- [x] 6.1 Update the README's provider-registration section with an "Azure OpenAI" subsection covering the required fields (base URL, API version), deployment-name terminology, the lack of auto-discovery, and the `reasoning_effort` setting.
- [x] 6.2 If implementation surfaces a decision not already captured in `design.md`'s Decisions, append it under a new "Implementation Notes" section (matching the convention used in prior archived changes); otherwise skip.
- [x] 6.3 Run `make lint` and `make test` (backend and frontend) and fix anything broken; run `openspec validate add-azure-openai-provider --strict` and confirm it passes.
