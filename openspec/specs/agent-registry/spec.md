# agent-registry Specification

## Purpose

Lets a user register a deployed AI agent with the platform, control how its live traffic is evaluated, and issue the credential the agent uses to stream its interactions in, without the platform ever hosting or launching the agent itself.

## Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot` or `reasoning`), and the model the agent declares it uses. On registration the system SHALL issue a single-use ingest token shown to the user exactly once.

#### Scenario: Successful registration
- **WHEN** the user registers an agent with a unique name, a kind and a declared model
- **THEN** the agent is created in a paused-until-first-event state, an ingest token is displayed once, and the token is never shown again in the UI or any API response

#### Scenario: Duplicate name rejected
- **WHEN** the user registers an agent whose name matches an existing agent
- **THEN** the request is rejected with a validation error and no agent is created

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
Saving an agent's evaluator list SHALL be rejected when it names the agent's declared model, so that the mistake is caught before any traffic is evaluated.

#### Scenario: Self-evaluator rejected at save time
- **WHEN** the user saves evaluation settings whose evaluator list includes the agent's declared model
- **THEN** the request is rejected with a validation error explaining that an agent cannot evaluate its own declared model, and the previous settings remain in effect

#### Scenario: Declared model can still differ from what actually runs
- **WHEN** the agent's declared model is accepted as distinct from its evaluators
- **THEN** registration succeeds, noting that the declared model is informational and the platform separately checks, at evaluation time, which models a turn actually used

### Requirement: Registering a hosted model as an evaluator requires acknowledging data sharing
When the user's evaluator list for an agent includes an enterprise (non-local) model, the system SHALL require an explicit acknowledgment that this agent's live conversations will be sent to that model's provider before the settings can be saved.

#### Scenario: Acknowledgment required
- **WHEN** the user adds a registered enterprise model as an evaluator for an agent and has not acknowledged data sharing for that agent
- **THEN** saving is blocked and the UI explains which provider will receive this agent's live traffic

#### Scenario: Acknowledgment recorded per agent
- **WHEN** the user acknowledges data sharing and saves
- **THEN** the acknowledgment is recorded against that agent and is not required again for the same provider on that agent, but is required again if a new provider is later added to its evaluators

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
