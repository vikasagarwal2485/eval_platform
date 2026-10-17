# Spec Delta

## MODIFIED Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot` or
`reasoning`), and one or more models the agent declares it uses, each keyed by the task it serves
(for example `reasoning`, `generation`, or `default` for an agent with a single undifferentiated
model). A declared model MAY be given as a plain model reference, or as an object carrying a model
reference plus optional generation-parameter overrides (for example a temperature) applied to
every call made for that task. On registration the system SHALL issue a single-use ingest token
shown to the user exactly once.

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
