# Spec Delta

## MODIFIED Requirements

### Requirement: An agent can discover its own registration
The system SHALL let a registered agent read back its own name, kind, declared models, and, for
each of its declared task types, either the gateway model group name computed for it or - when
that task's declared model resolves to a provider with no gateway deployment to route to (a
`custom`-kind provider) - that provider's base URL and the model's id, so an agent can locate a
non-gateway-routed dependency the same way it already locates a gateway-routed one. This is
authenticated by the same ingest token it uses to send events. The response SHALL NOT include the
ingest token itself, any gateway credential, or any provider secret.

#### Scenario: An agent reads its own identity and group names
- **WHEN** an agent calls the self-discovery endpoint with its own valid ingest token
- **THEN** the response includes that agent's registered name, kind, declared models, and the
  exact gateway model group name the platform would use (or has used) to sync each declared task
  type, computed the same way the platform's own gateway sync computes it

#### Scenario: An invalid or missing token is rejected
- **WHEN** the self-discovery endpoint is called without a valid ingest token
- **THEN** the request is rejected as unauthorized and no agent's registration is returned

#### Scenario: A paused agent can still discover itself
- **WHEN** a paused agent calls the self-discovery endpoint with its still-valid ingest token
- **THEN** the request succeeds and returns its registration, since discovering its own identity is
  not the same as sending it live traffic

#### Scenario: No secret is ever returned
- **WHEN** any agent calls the self-discovery endpoint
- **THEN** the response contains only its name, kind, declared models and computed gateway group
  names, and never its ingest token, a gateway credential, or a provider secret

#### Scenario: A declared task backed by a custom-kind provider exposes its address, not a gateway group
- **WHEN** an agent calls the self-discovery endpoint and one of its declared task types resolves
  to a `custom`-kind provider
- **THEN** that task type is absent from the response's gateway-group names, and the response
  instead gives that provider's base URL and the declared model's id for that task type

#### Scenario: A custom provider's base URL is not treated as a secret
- **WHEN** the self-discovery response includes a `custom`-kind provider's base URL for a declared
  task type
- **THEN** that URL is returned as-is, since it is an address to call, not a credential - unlike an
  ingest token, gateway credential or provider secret, which are never returned

### Requirement: Registering a hosted model as an evaluator requires acknowledging data sharing
When the user's evaluator list for an agent includes an enterprise (non-local) model, the system
SHALL require an explicit acknowledgment that this agent's live conversations will be sent to that
model's provider before the settings can be saved. The same acknowledgment is required when a
declared model's primary or fallback reference is an enterprise model, since either may carry this
agent's live conversations to that provider. A reference to a `custom`-kind provider is exempt,
like an `ollama` one, but for a different reason: the platform itself never sends this agent's data
to a `custom`-kind provider at all - only the agent's own code calls it directly, if it chooses to -
so there is nothing here for the platform to ask the user to acknowledge.

#### Scenario: Acknowledgment required
- **WHEN** the user adds a registered enterprise model as an evaluator for an agent and has not acknowledged data sharing for that agent
- **THEN** saving is blocked and the UI explains which provider will receive this agent's live traffic

#### Scenario: Acknowledgment recorded per agent
- **WHEN** the user acknowledges data sharing and saves
- **THEN** the acknowledgment is recorded against that agent and is not required again for the same provider on that agent, but is required again if a new provider is later added to its evaluators

#### Scenario: Acknowledgment required for a hosted fallback
- **WHEN** the user sets a declared model's fallback to a registered enterprise model and has not
  acknowledged data sharing with that provider for this agent
- **THEN** saving is blocked exactly as it would be for a hosted evaluator or a hosted primary
  declared model

#### Scenario: A custom-kind reference needs no acknowledgment
- **WHEN** a declared model's primary or fallback reference resolves to a registered `custom`-kind
  provider
- **THEN** registration or settings saving succeeds without requiring (or offering) a data-sharing
  acknowledgment for that provider
