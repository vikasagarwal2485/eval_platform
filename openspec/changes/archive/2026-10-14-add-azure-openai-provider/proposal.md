# Proposal

## Why

Azure OpenAI is a common way enterprises access OpenAI models, and it is not interchangeable with the official OpenAI API despite sharing the same request/response shape for chat completions: it needs an `api-key` header instead of `Authorization: Bearer`, a deployment-scoped URL (`{resource}/openai/deployments/{deployment}/chat/completions`) instead of a `model` field in the body, and a mandatory `api-version` query parameter on every call. Registering an Azure OpenAI resource today as a `kind: "openai"` provider with a custom Base URL silently falls back to `https://api.openai.com` whenever a field (like `api-version`) is missing, or 404s against Azure's real endpoint otherwise - "Test connection" then reports a confusing, misleading failure (OpenAI's own "incorrect API key" error, for a key OpenAI never saw) rather than a clear statement that Azure isn't supported yet. Enterprises using Azure OpenAI cannot register it at all today.

## What Changes

- Add a new, distinct provider kind `azure-openai`, alongside the existing `openai` and `anthropic` kinds, with its own adapter, capabilities, and UI treatment.
- Require `base_url` (the Azure resource endpoint) and a new `api_version` field when registering an `azure-openai` provider; both are provider-level, since Azure ties them to the resource rather than to each call.
- Build Azure requests against `{base_url}/openai/deployments/{deployment}/chat/completions?api-version={api_version}`, authenticated with an `api-key` header, reusing the existing OpenAI streaming/parsing logic (the chat-completions chunk shape is the same).
- Treat what the user registers as a "model" for an `azure-openai` provider as the Azure **deployment name**; the UI labels this field "Deployment name" for this kind instead of "Model id".
- "Discover a provider's models" (fetch-and-add) is not offered for `azure-openai`: there is no inference-plane endpoint to list deployments (that needs Azure Resource Manager and Azure AD auth, a different credential scheme entirely), so the UI states this plainly and the user adds deployment names directly.
- "Test a provider connection" for `azure-openai` requires at least one registered deployment (there is no provider-wide endpoint to ping); with none registered, the action explains that instead of attempting a call. With one, it sends a minimal chat completion to that deployment, which validates the key, `api-version`, and deployment together.
- Add a `reasoning_effort` setting for models flagged as reasoning models, applied the same way for both `openai` and `azure-openai`, recorded through the existing applied/ignored parameter mechanism.

## Capabilities

### New Capabilities
(none - this extends the existing enterprise-provider capabilities with a new provider kind rather than introducing a new domain)

### Modified Capabilities
- `model-providers`: a new `azure-openai` provider kind with required `base_url` and a new `api_version` field, deployment-name terminology, a no-discovery scenario, and a test-connection precondition requiring a registered deployment.
- `enterprise-model-execution`: a new Azure OpenAI backend (deployment-scoped request path, `api-key` auth, `api-version` query parameter) and a `reasoning_effort` parameter mapped for flagged reasoning models on both `openai` and `azure-openai`.

## Impact

- Backend: `app/providers/azure_openai.py` (new adapter), `app/providers/backend.py` (`CLOUD_CAPS["azure-openai"]`, `ProviderConfig.api_version`), `app/providers/factories.py` (new factory), `app/providers/openai.py` (shared `reasoning_effort` mapping), `app/api/providers.py` (schema validation: required `base_url`/`api_version` for `azure-openai`, no-discovery response, test-connection precondition), `app/models.py` + an Alembic migration (`Provider.api_version` column).
- Frontend: `frontend/src/lib/providers.ts` (new kind label/defaults), `frontend/src/components/ProviderForm.tsx` (conditional required fields, deployment-name label), `frontend/src/components/ProviderCard.tsx` (no-discovery state, test-connection precondition messaging).
- Tests: a fake Azure OpenAI test double alongside the existing `FakeOpenAI`/`FakeAnthropic`, adapter unit tests (URL/header/api-version construction, `reasoning_effort` mapping), API tests for the new validation and no-discovery/test-connection behavior, and an extension of the secret-leak scan to Azure's key shape.
- Docs: README's provider-registration section gains an Azure OpenAI subsection (required fields, deployment-name terminology, no auto-discovery).
