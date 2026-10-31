# gateway-model-sync Specification

## Purpose

Keeps the shared LLM gateway's per-agent model groups consistent with what each agent's
`declared_models` actually says, so an operator configures a model and its generation parameters
once, in the registry, instead of maintaining the same information by hand in the gateway's own
configuration.

## Requirements

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

### Requirement: A declared model's fallback is synced to its own gateway group
When an agent's declared model for a task type specifies a fallback model reference, the system
SHALL create, update or remove a second gateway model group for that task type - scoped to the
agent the same way the primary group is - configured with the fallback's resolved deployment.

#### Scenario: A declared fallback gets a matching fallback gateway group
- **WHEN** an agent's declared model for a task type specifies a fallback model reference
- **THEN** the system creates a gateway model group for that task type's fallback, configured with
  the fallback model's resolved deployment, in addition to the existing primary group

#### Scenario: A changed fallback updates the existing fallback gateway group
- **WHEN** an agent's fallback for a task type is changed to a different model or different
  generation parameters
- **THEN** the system updates that task type's existing fallback gateway group to match, rather
  than leaving the old configuration in place or creating a duplicate

#### Scenario: Removing a fallback removes its gateway group
- **WHEN** a previously configured fallback is removed from a declared model, the declared model
  itself is removed, or its task type is removed entirely
- **THEN** the system removes that task type's fallback gateway group so it can no longer be
  routed to

### Requirement: A declared model that is not gateway-routable is never synced as an error
When an agent's declared model for a task type resolves to a provider kind that has no
chat-completions-shaped gateway deployment to create (a `custom`-kind provider), the system SHALL
report that task type's sync outcome as explicitly not applicable, rather than as a sync error, and
SHALL NOT attempt to create, update or remove any gateway model group for it.

#### Scenario: A custom-kind declared model is reported as not gateway-routed, not an error
- **WHEN** an agent is registered or updated with a declared model for a task type that resolves
  to a `custom`-kind provider
- **THEN** that task type's sync result reports it is not gateway-routed, the request otherwise
  succeeds, and no gateway model group is created, updated or queried for that task type

#### Scenario: A previously gateway-routed task type switched to a custom-kind model removes its old group
- **WHEN** a task type's declared model is changed from one that resolved to a gateway-routable
  provider to one that resolves to a `custom`-kind provider
- **THEN** the system removes that task type's existing gateway model group (it is no longer
  routable) and reports the task type as not gateway-routed, not as an error

### Requirement: A playground-eligible agent's gateway virtual key is minted and kept in sync
When an agent is marked playground-eligible (`agent-playground`), the system SHALL mint a gateway
virtual key scoped to exactly that agent's own currently-synced model groups (primary and
fallback), store it for later spawn use, and re-mint it whenever those synced groups change, so
the stored key never grants access to a group the agent no longer declares, nor lacks access to
one it just gained.

#### Scenario: Marking an agent eligible mints its first key
- **WHEN** an agent with already-synced model groups is marked playground-eligible
- **THEN** the system mints a gateway virtual key allow-listing exactly that agent's current
  primary and fallback groups and stores it

#### Scenario: A changed declared model re-mints the key before next use
- **WHEN** a playground-eligible agent's declared models change, adding, removing or altering a
  task's gateway group
- **THEN** the system re-mints the stored virtual key to allow-list the updated set of groups,
  discarding the previous key's value

#### Scenario: A non-eligible agent never gets a key minted
- **WHEN** an agent is not playground-eligible
- **THEN** the system never calls the gateway's key-minting endpoint on its behalf, and an operator
  wishing to run it manually continues to mint and manage its virtual key by hand, exactly as
  before this change

#### Scenario: A minting failure is reported, not silently swallowed
- **WHEN** the gateway is unreachable or rejects a key-minting attempt for a playground-eligible
  agent
- **THEN** the triggering request (marking eligible, or the declared-model change) still succeeds,
  and the response reports that key minting did not succeed, mirroring how a model-group sync
  failure is already reported without blocking the request

#### Scenario: Explicit rotation re-mints and discards the previous key
- **WHEN** the user explicitly requests credential rotation for a playground-eligible agent
- **THEN** the system mints a new virtual key scoped to its current groups and discards the
  previous key's value, the same way an ingest-token rotation invalidates the previous token
