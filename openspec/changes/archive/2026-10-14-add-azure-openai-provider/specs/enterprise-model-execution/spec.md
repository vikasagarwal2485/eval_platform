# Spec Delta

## ADDED Requirements

### Requirement: Call Azure OpenAI deployments through their deployment-scoped endpoint
For a provider of kind `azure-openai`, the backend SHALL send the API key in the provider's `api-key` header rather than as a bearer token, SHALL address the request to the registered deployment via a deployment-scoped path, and SHALL include the provider's configured API version as a query parameter on every request. Answer text, usage and model version SHALL be recorded the same way as for an `openai` provider.

#### Scenario: Deployment-scoped request
- **WHEN** a run calls a model registered under an `azure-openai` provider
- **THEN** the request is sent to that provider's base URL with the registered deployment name in the path and the provider's API version in the query string

#### Scenario: API key header
- **WHEN** the backend calls an `azure-openai` provider
- **THEN** the key is sent in the `api-key` header, never as an `Authorization` bearer token

#### Scenario: Same response handling as OpenAI
- **WHEN** an `azure-openai` deployment streams a chat completion
- **THEN** the answer, usage, and model version are recorded the same way as for an `openai` provider

## MODIFIED Requirements

### Requirement: Map and record run parameters per provider
The backend SHALL apply the run's sampling temperature and maximum output tokens to enterprise requests, SHALL apply the seed and context-size settings only where the provider supports them, and SHALL apply a configured reasoning-effort level to models flagged as reasoning models where the provider supports it. For every enterprise result the system SHALL record which parameters were applied and which were ignored or altered, and why.

#### Scenario: Seed not supported
- **WHEN** a run with a seed includes a model whose provider does not accept one
- **THEN** the request omits it and the result records that the seed was not applied

#### Scenario: Parameter rejected for a reasoning model
- **WHEN** a model does not accept a temperature setting
- **THEN** the request omits or adjusts it as the provider requires and the result records the adjustment

#### Scenario: Visible in results
- **WHEN** the user views a result that had ignored parameters
- **THEN** the drill-down shows them so runs are not presented as more reproducible than they were

#### Scenario: Reasoning effort applied
- **WHEN** a run includes a model flagged as a reasoning model with a configured reasoning-effort level
- **THEN** the request includes it and the result records it as applied

#### Scenario: Reasoning effort not applicable
- **WHEN** a model is not flagged as a reasoning model
- **THEN** any configured reasoning-effort level is not sent and is not recorded as applied
