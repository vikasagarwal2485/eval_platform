# agent-registry Specification

## Purpose

Lets a user register a deployed AI agent with the platform, control how its live traffic is evaluated, and issue the credential the agent uses to stream its interactions in, without the platform ever hosting or launching the agent itself.

## Requirements

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
