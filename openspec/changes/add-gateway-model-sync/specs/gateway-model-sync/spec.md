# Spec Delta

## Purpose

Keeps the shared LLM gateway's per-agent model groups consistent with what each agent's
`declared_models` actually says, so an operator configures a model and its generation parameters
once, in the registry, instead of maintaining the same information by hand in the gateway's own
configuration.

## ADDED Requirements

### Requirement: Declared models are synced to the gateway on change
Whenever an agent is created, or its `declared_models` are updated, the system SHALL attempt to
create, update or remove the gateway's model group for each affected task type so that it matches
the agent's current declared model and any generation-parameter overrides for that task.

#### Scenario: A new declared model gets a matching gateway group
- **WHEN** an agent is registered with a declared model for a task type that has no existing
  gateway group
- **THEN** the system creates a gateway model group named for that agent and task type, configured
  with the declared model and any generation-parameter overrides

#### Scenario: A changed declared model updates the existing gateway group
- **WHEN** an agent's declared model for a task type is changed to a different model or different
  generation parameters
- **THEN** the system updates that task type's existing gateway group to match, rather than
  leaving the old configuration in place or creating a duplicate

#### Scenario: A removed declared model removes its gateway group
- **WHEN** a task type is removed from an agent's declared models
- **THEN** the system removes that task type's gateway model group so it can no longer be routed
  to

### Requirement: A sync failure never blocks saving agent settings
When the gateway is unreachable or rejects a sync attempt, the system SHALL still save the
agent's declared models and SHALL report the sync failure to the caller, rather than rejecting the
whole request - not every agent depends on the gateway being reachable.

#### Scenario: Registration succeeds despite a gateway sync failure
- **WHEN** the gateway is unreachable while an agent is being registered with declared models that
  would otherwise sync to it
- **THEN** the agent is still created with those declared models, and the response indicates the
  gateway sync did not succeed

#### Scenario: An agent that never uses the gateway is unaffected
- **WHEN** an agent whose own code never calls the gateway (for example the reference chatbot
  agent) is registered or updated
- **THEN** a gateway sync is still attempted for its declared models, and its failure or success
  has no other effect on that agent's registration

### Requirement: A provider credential is never sent to the gateway in the clear
When syncing a declared model that references an enterprise provider, the system SHALL pass that
provider's credential to the gateway only as an environment-variable reference, never as a literal
value, mirroring how the platform's own `ModelRouter` already handles provider credentials.

#### Scenario: An enterprise-provider declared model syncs without exposing its key
- **WHEN** a declared model referencing a registered enterprise provider is synced to the gateway
- **THEN** the gateway receives only the name of the environment variable holding that provider's
  key, never the key's value
