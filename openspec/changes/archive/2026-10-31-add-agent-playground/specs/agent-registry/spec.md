# Spec Delta

## MODIFIED Requirements

### Requirement: Register an agent
The system SHALL let the user register an agent by giving it a unique name, a kind (`chatbot`,
`reasoning`, or `router`), and one or more models the agent declares it uses, each keyed by the
task it serves (for example `reasoning`, `generation`, or `default` for an agent with a single
undifferentiated model). A declared model MAY be given as a plain model reference, or as an object
carrying a model reference plus optional generation-parameter overrides (for example a
temperature) applied to every call made for that task. Each declared model MAY also specify a
fallback model reference, validated the same way as the primary reference, for the platform to use
when the primary becomes unreachable. A `router`-kind agent SHALL also be given one or more
hand-off agents (`handoff_agent_names`) at registration time - mandatory for that kind, since a
router with none configured could never hand a problem off to anything; meaningless, and required
to be empty, for any other kind. On registration the system SHALL issue a single-use ingest token
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

#### Scenario: A declared model's fallback is validated like its primary
- **WHEN** the user registers or updates an agent with a declared model whose fallback reference is
  not a valid model reference
- **THEN** the request is rejected with a validation error naming the invalid fallback, exactly as
  an invalid primary reference would be

#### Scenario: A classifier-router orchestrator registers under its own kind
- **WHEN** the user registers an agent that classifies and routes to other agents rather than
  reasoning through a problem itself (for example the reference classifier-router agent)
- **THEN** it is registered with `kind: "router"`, rather than reusing `reasoning`'s kind and its
  built-in rubric

#### Scenario: Existing reasoning-kind registrations are unaffected
- **WHEN** an agent already registered with `kind: "reasoning"` (including one that is actually a
  classifier-router agent registered before this change) is read or updated
- **THEN** its `kind` remains `reasoning` unless the user explicitly changes it; this change only
  affects what kind a *new* classifier-router registration should use

#### Scenario: A router agent names one or more hand-off targets by name
- **WHEN** the user registers or updates a `router`-kind agent with `handoff_agent_names` naming
  one or more existing, registered agents of any kind
- **THEN** the request succeeds and the named agents (each identified by its unique, user-facing
  name, never an internal id the user does not see) are recorded as this router's hand-off targets

#### Scenario: A router is not limited to a single hand-off target
- **WHEN** the user registers or updates a `router`-kind agent with more than one entry in
  `handoff_agent_names`
- **THEN** the request succeeds - the registry places no limit on how many hand-off targets a
  router may declare, independent of whether any one catalog flavor's own script is able to use
  more than one of them at spawn time (`agent-playground`)

#### Scenario: A router-kind agent must declare at least one hand-off target
- **WHEN** the user registers or updates a `router`-kind agent with an empty `handoff_agent_names`
- **THEN** the request is rejected with a validation error, since a router with no hand-off target
  could never actually hand a problem off to anything

#### Scenario: Hand-off targets are rejected for a non-router kind
- **WHEN** the user sets a non-empty `handoff_agent_names` on an agent whose `kind` is not `router`
- **THEN** the request is rejected with a validation error, since only a router ever hands a
  problem off to another agent

#### Scenario: Each hand-off target must already be a registered agent
- **WHEN** any entry in a `router`-kind agent's `handoff_agent_names` does not match any registered
  agent
- **THEN** the request is rejected with a validation error naming the problem, rather than
  recording a hand-off target that could never actually be spawned

#### Scenario: A hand-off target's own kind is unconstrained
- **WHEN** the user names an existing, registered agent of any kind (`chatbot`, `reasoning`, or
  `router`) in a `router`-kind agent's `handoff_agent_names`
- **THEN** the request succeeds - a hand-off target's own registered kind is purely descriptive of
  that agent's own registration and is never validated against what spawning it would actually run
  (`agent-playground`)

#### Scenario: A router cannot name itself as one of its own hand-off targets
- **WHEN** a `router`-kind agent's `handoff_agent_names` includes its own name
- **THEN** the request is rejected with a validation error

#### Scenario: Hand-off targets must be distinct
- **WHEN** a `router`-kind agent's `handoff_agent_names` names the same agent more than once
- **THEN** the request is rejected with a validation error
