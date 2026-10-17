# Spec Delta

## MODIFIED Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot` or
`reasoning`), and one or more models the agent declares it uses, each keyed by the task it serves
(for example `reasoning`, `generation`, or `default` for an agent with a single undifferentiated
model). On registration the system SHALL issue a single-use ingest token shown to the user exactly
once.

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
