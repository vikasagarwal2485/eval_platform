# agent-registry Specification

## Purpose

Lets a user register a deployed AI agent with the platform, control how its live traffic is evaluated, and issue the credential the agent uses to stream its interactions in, without the platform ever hosting or launching the agent itself.

## Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot` or
`reasoning`), and one or more models the agent declares it uses, each keyed by the task it serves
(for example `reasoning`, `generation`, or `default` for an agent with a single undifferentiated
model). A declared model MAY be given as a plain model reference, or as an object carrying a model
reference plus optional generation-parameter overrides (for example a temperature) applied to
every call made for that task. Each declared model MAY also specify a fallback model reference,
validated the same way as the primary reference, for the platform to use when the primary becomes
unreachable. On registration the system SHALL issue a single-use ingest token shown to the user
exactly once.

#### Scenario: Successful registration
- **WHEN** the user registers an agent with a unique name, a kind and one or more declared models
- **THEN** the agent is created in a paused-until-first-event state, an ingest token is displayed
  once, and the token is never shown again in the UI or any API response

#### Scenario: Duplicate name rejected
- **WHEN** the user registers an agent whose name matches an existing agent
- **THEN** the request is rejected with a validation error and no agent is created

#### Scenario: At least one declared model is required
- **WHEN** the user attempts to register an agent with no declared models
- **THEN** the request is rejected with a validation error, since an agent with no declared model
  cannot be checked against its evaluator list

#### Scenario: An agent with a single task declares one model
- **WHEN** the user registers an agent that performs only one undifferentiated task (for example
  the reference chatbot agent)
- **THEN** a single declared model under a conventional key is sufficient and valid

#### Scenario: A declared model may carry generation-parameter overrides
- **WHEN** the user declares a model as an object with a `params` field (for example
  `{"model": "...", "params": {"temperature": 0.2}}`) instead of a plain string
- **THEN** registration succeeds, and those parameters are the ones later synced to that task
  type's gateway model group

#### Scenario: A plain string declared model still works unchanged
- **WHEN** the user declares a model as a plain reference string, exactly as before this change
- **THEN** registration succeeds identically to today, with no generation-parameter overrides

#### Scenario: A declared model's fallback is validated like its primary
- **WHEN** the user registers or updates an agent with a declared model whose fallback reference is
  not a valid model reference
- **THEN** the request is rejected with a validation error naming the invalid fallback, exactly as
  an invalid primary reference would be

### Requirement: Ingest tokens are never stored or displayed in the clear after issuance
The system SHALL store only a salted hash of each ingest token plus a short prefix for display, SHALL compare presented tokens without revealing the stored value, and SHALL let the user rotate a token, immediately invalidating the previous one.

#### Scenario: Token shown once
- **WHEN** the user issues or rotates an agent's ingest token
- **THEN** the full token is shown once in that response and no later read of the agent returns anything but the prefix

#### Scenario: Rotation invalidates the old token
- **WHEN** the user rotates an agent's token and an event batch then arrives bearing the previous token
- **THEN** the batch is rejected as unauthorized

### Requirement: Configure evaluation settings per agent
The system SHALL let the user configure, per agent, the ordered list of evaluator models, an optional custom rubric, a sample rate, a quiet period, the number of prior turns of context to include, an attention threshold, and an abandoned-turn timeout. Each setting SHALL have a documented default so an agent can be registered without configuring any of them.

#### Scenario: Defaults apply when unset
- **WHEN** the user registers an agent without setting evaluation options
- **THEN** the agent evaluates every turn with the built-in rubric for its kind at a sample rate of 100%, using the platform's default quiet period, context window, attention threshold and abandonment timeout

#### Scenario: Invalid sample rate rejected
- **WHEN** the user sets a sample rate outside 0 to 1, or a negative quiet period, context-turn count or timeout
- **THEN** the request is rejected with a validation error naming the invalid field and existing settings are unchanged

### Requirement: An evaluator cannot be configured as an agent's own model
Saving an agent's evaluator list SHALL be rejected when it names any of the agent's declared
models, so that the mistake is caught before any traffic is evaluated, regardless of which
declared model a given turn ends up actually using.

#### Scenario: Self-evaluator rejected at save time
- **WHEN** the user saves evaluation settings whose evaluator list includes any one of the agent's
  declared models
- **THEN** the request is rejected with a validation error naming the conflicting model, and the
  previous settings remain in effect

#### Scenario: Declared model can still differ from what actually runs
- **WHEN** the agent's declared models are accepted as distinct from its evaluators
- **THEN** registration succeeds, noting that declared models are informational and the platform
  separately checks, at evaluation time, which models a turn actually used

#### Scenario: A multi-model agent is checked against all of its declared models, not just one
- **WHEN** an agent declares both a `reasoning` and a `generation` model, and the user configures
  an evaluator that matches only the `generation` model
- **THEN** the save is still rejected, exactly as if it had matched the `reasoning` model

### Requirement: Registering a hosted model as an evaluator requires acknowledging data sharing
When the user's evaluator list for an agent includes an enterprise (non-local) model, the system SHALL require an explicit acknowledgment that this agent's live conversations will be sent to that model's provider before the settings can be saved. The same acknowledgment is required when a declared model's primary or fallback reference is an enterprise model, since either may carry this agent's live conversations to that provider.

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

### Requirement: An agent can discover its own registration
The system SHALL let a registered agent read back its own name, kind, declared models, and the
gateway model group name computed for each of its declared task types, authenticated by the same
ingest token it uses to send events. The response SHALL NOT include the ingest token itself, any
gateway credential, or any provider secret.

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

### Requirement: Pause, resume and delete an agent
The system SHALL let the user pause an agent (rejecting further ingest with a clear status so a well-behaved SDK stops retrying), resume it, and delete it. Deleting an agent SHALL remove its sessions, turns, spans and evaluations.

#### Scenario: Paused agent's events are rejected
- **WHEN** an event batch arrives for a paused agent
- **THEN** the batch is rejected with a status indicating the agent is paused, and nothing is stored

#### Scenario: Delete cascades
- **WHEN** the user deletes an agent that has recorded sessions and evaluated turns
- **THEN** the agent and all of its sessions, turns, spans and evaluations are removed, and its ingest token no longer authenticates

### Requirement: Agent liveness is visible
The system SHALL record when each agent last sent an event and SHALL derive a liveness status (live, idle, offline, paused) from it for display.

#### Scenario: Status reflects recent activity
- **WHEN** an agent has sent an event within the last minute
- **THEN** it is shown as live; after a longer period of silence it is shown as idle, then offline, without any event being required to mark it so
