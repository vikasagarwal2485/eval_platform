# Spec Delta

## MODIFIED Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot` or
`reasoning`), and one or more models the agent declares it uses, each keyed by the task it serves
(for example `reasoning`, `generation`, or `default` for an agent with a single undifferentiated
model). Each declared model MAY also specify a fallback model reference, validated the same way as
the primary reference, for the platform to use when the primary becomes unreachable. On
registration the system SHALL issue a single-use ingest token shown to the user exactly once.

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

#### Scenario: A declared model's fallback is validated like its primary
- **WHEN** the user registers or updates an agent with a declared model whose fallback reference is
  not a valid model reference
- **THEN** the request is rejected with a validation error naming the invalid fallback, exactly as
  an invalid primary reference would be

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
