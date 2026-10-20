# Tasks

## 1. Data model

- [x] 1.1 Add `Provider.kind == "custom"` support (no schema change needed for `kind` itself - it's
      already a free `String(20)`) and a nullable `health_check_path` column; write Alembic
      migration `0011` (mirroring `0010`'s pattern) and verify
      `test_migration_matches_models`/`test_alembic_upgrade_head_creates_all_tables` pass

## 2. Backend: registration and availability

- [x] 2.1 Extend `ProviderIn`/`ProviderUpdate` (and `repo.create_provider`/`update_provider`) to
      accept `kind="custom"` with `key_env` omitted and `health_check_path` optional, require a
      `base_url`; verify a test registers a custom provider with no key-env field and rejects one
      with no base URL
- [x] 2.2 Extend `provider_availability()`'s key-presence check from `kind != "ollama"` to `kind not
      in ("ollama", "custom")`; verify a test confirms a custom provider with no key is reported
      available (not "key not set") purely on that basis
- [x] 2.3 Extend `repo._check_provider_acks()`'s `kind == "ollama"` exemption to also cover
      `kind == "custom"` (found during task 6.1's implementation - the platform never sends this
      agent's data to a `custom`-kind provider itself, so there is nothing to acknowledge); verify a
      test registers an agent with a declared model (and, separately, a fallback) referencing a
      `custom`-kind provider with no acknowledgment and no `AckRequired` error

## 3. Backend: models under a custom provider

- [x] 3.1 Verify `POST /providers/{id}/models` already works unmodified for a custom provider (add
      by typing an id, enable/disable, remove - no kind-specific logic in that path today); add a
      test registering a model under a custom provider to confirm
- [x] 3.2 Verify `GET /providers/{id}/available-models` (auto-discovery) is refused for `custom`
      the same way it already is for `azure-openai` (409/`not_supported`, explaining why); add a
      test for the custom case specifically

## 4. Backend: "Test connection" without a chat call

- [x] 4.1 Add the `kind == "custom"` branch to `test_provider()`: a plain HTTP GET to
      `base_url + (health_check_path or "/health")`, mapping a successful response to "working" and
      a connection/timeout failure to "unreachable", never attempting `_backend()`/`chat_stream()`;
      verify tests for both outcomes against a fake HTTP server

## 5. Backend: gateway sync never errors on a custom-kind declared model

- [x] 5.1 Add the custom-kind short-circuit to `gateway_sync` (checked before the existing
      `_LITELLM_PROVIDER_PREFIX` lookup): a declared model resolving to a `custom`-kind provider
      reports its task type's sync outcome as explicitly not-gateway-routed (a new status string,
      not `"error"`), and no `/model/new`/`/model/update`/`/model/delete` call is ever attempted
      for it; verify a test registering an agent with a custom-kind declared model shows that clean
      status, not the existing unknown-kind error message
- [x] 5.2 Verify switching a task type's declared model from a gateway-routable provider to a
      custom-kind one removes its existing gateway group (via the existing delete path) and still
      reports not-gateway-routed, not an error

## 6. Backend: self-discovery exposes a custom provider's address

- [x] 6.1 Extend `GET /api/ingest/v1/whoami`'s handler to resolve each declared task's provider
      kind (a cloud ref only; a bare/local ref is unaffected) and, for a `custom`-kind resolution,
      omit that task from `gateway_model_groups` and add it to a new `custom_model_endpoints`
      object (`{"<task>": {"base_url": ..., "model_id": ...}}`) instead; verify a test confirms the
      existing three task-resolution shapes (bare, enterprise, previously-unresolvable) are
      byte-for-byte unchanged, and a new test confirms the custom-kind shape
- [x] 6.2 Verify no secret leaks through the new field: a test confirms `custom_model_endpoints`
      never contains anything beyond `base_url`/`model_id` (no gateway credential, no provider
      secret, no ingest token) for any custom-kind provider, including one whose name or base URL
      is adversarially chosen to resemble a secret-looking string

## 7. Frontend

- [x] 7.1 Add `custom` to `ProviderForm.tsx`'s kind `<select>` and `KIND_LABEL`; hide the key-env
      field for it (same pattern as `isOllama`) and show an optional health-check-path field only
      for it; verify a component test registers a custom provider through the form with no
      key-env value entered
- [x] 7.2 Extend `ProviderCard.tsx`'s "no key needed" badge condition from `isOllama` to `isOllama
      || isCustom`; verify a test shows the badge for a registered custom provider
- [x] 7.3 Verify `ModelPicker.tsx`/`DeclaredModelPicker.tsx`/`EvaluatorPicker.tsx` never offer a
      custom-kind model (they already only ever render what `/api/models` returns, and this change
      does not add custom-kind models to that endpoint) - a regression test confirming a registered
      custom model does not appear in any of the three pickers

## 8. End-to-end verification against the spec

- [x] 8.1 Register a live custom provider against a locally running fake HTTP service (health
      endpoint + one arbitrary other route), test its connection (both reachable and unreachable
      cases), add a model under it, and confirm the Models page shows it correctly with no key
      field
- [x] 8.2 Register a test agent with a declared model for one task pointing at the custom
      provider's model and another task pointing at a normal gateway-routable model; verify (a) the
      agent's create/update response shows the custom task's sync status as not-gateway-routed, not
      an error, while the other task syncs normally, and (b) `GET /api/ingest/v1/whoami` returns
      `gateway_model_groups` for the normal task and `custom_model_endpoints` for the custom one,
      live against a running platform and gateway
