# Spec Delta

## ADDED Requirements

### Requirement: A reference classifier-routed multi-agent orchestrator is provided
The system SHALL ship a runnable reference agent that, for each turn, first classifies the
incoming problem using an external, non-LLM classification service - whose address the agent
discovers from its own registration, like every other task-scoped dependency it uses, unless an
explicit override is given - then makes a gateway-routed LLM call that decides, via a tool call,
which of at least two distinct downstream actions to take, and finally either hands the problem
off to a different, independently registered reference agent or finishes the turn immediately with
no further model call. Every real LLM call this agent makes SHALL be routed through the shared LLM
gateway (`agent-llm-gateway`) by a task-scoped model group name the agent discovers for itself,
exactly like the platform's other reference agents; this agent SHALL NOT call any LLM provider
directly under any circumstance.

#### Scenario: A turn classifies before it routes
- **WHEN** the reference classifier-routed agent begins answering a problem
- **THEN** it first calls the external classification service and records the result as a `tool`
  span (not an `llm` span, since no gateway-routed model produced it), before any LLM call is made
  for that turn

#### Scenario: The agent discovers the classification service's address at startup
- **WHEN** the agent starts without an explicit override and successfully reads its own
  registration from the platform
- **THEN** it reaches the classification service at the address its own registration names for
  that task, not a hardcoded default, even when this agent is registered under a different name

#### Scenario: An explicit override still wins for the classification service's address
- **WHEN** the agent is started with an explicit classifier-address override
- **THEN** that address is used regardless of what the agent's own registration names for the
  task, and discovery's result for it is not consulted

#### Scenario: The routing decision is a gateway-routed, self-discovered LLM call
- **WHEN** the agent makes its routing-decision call for a turn
- **THEN** that call is addressed to the agent's own discovered (or explicitly overridden)
  routing-scoped model group, the resulting span records the concrete model the gateway actually
  used, and a fallback model group configured for this task is used when the primary deployment
  for it fails, the same way the platform's other reference agents already behave

#### Scenario: A gateway failure does not silently fall back to a direct provider call
- **WHEN** the shared gateway is unreachable during the agent's routing-decision call
- **THEN** that call fails visibly rather than the agent silently calling a provider directly,
  bypassing the gateway

#### Scenario: The routing decision resolves through a tool call, not a hardcoded branch
- **WHEN** the agent's routing-decision call completes
- **THEN** its result comes from invoking a tool that resolves the classification result to a
  concrete downstream action, rather than the agent's own code branching directly on the
  classifier's raw labels

#### Scenario: One branch hands off to a different, independently registered agent
- **WHEN** the resolved action is to solve the problem
- **THEN** the orchestrator hands the problem to a separate, independently registered reference
  agent to produce the actual answer, that agent's own interactions appear under its own identity
  in the platform (not attributed to the orchestrator's spans), and the orchestrator's own turn
  records the hand-off and its result as a `tool` span

#### Scenario: A different branch finishes without any further model call
- **WHEN** the resolved action is one that needs no further reasoning or generation (for example,
  a rejected/short-circuited case)
- **THEN** the orchestrator's turn finishes with its final output directly, and makes no further
  LLM call or hand-off for that turn

#### Scenario: The external classification call is exempt from the gateway-only constraint
- **WHEN** the agent calls the external classification service
- **THEN** that call is explicitly not subject to the "every LLM call goes through the gateway"
  requirement, because the classification service is not a generative model call

### Requirement: A routing-mapping tool resolves classification results to a target action
The system SHALL ship a standalone tool, reachable over a tool-calling protocol, that resolves a
classification result to a target downstream action using a mapping that can be changed without
modifying the orchestrator agent's own code.

#### Scenario: A known classification result resolves to its configured action
- **WHEN** the tool is called with a classification result that matches a configured mapping entry
- **THEN** it returns the action (and, where applicable, which other agent to hand off to)
  configured for that entry

#### Scenario: The mapping can be extended without touching the orchestrator's own logic
- **WHEN** an operator adds a new mapping entry for a classification result not previously handled
- **THEN** the orchestrator routes that case according to the new entry on its next call, without
  any change to the orchestrator agent's own code

#### Scenario: An unmapped classification result does not guess a target
- **WHEN** the tool is called with a classification result that matches no configured mapping
  entry
- **THEN** it reports that no route matched, and the orchestrator's turn ends in a visible error
  rather than guessing a downstream action
