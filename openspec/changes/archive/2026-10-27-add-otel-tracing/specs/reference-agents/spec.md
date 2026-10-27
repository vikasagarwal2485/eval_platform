# Spec Delta

## MODIFIED Requirements

### Requirement: A reference chatbot agent is provided
The system SHALL ship a runnable chatbot agent that answers user messages using a configurable local model, sends each exchange as one turn with one LLM span to the platform using the agent SDK, and works against the same test infrastructure the platform's own tests use. That span SHALL be a real OpenTelemetry span (`trace-observability`), not a custom ingest event, so the exchange is viewable as a trace in Tempo/Grafana and in the platform's own frontend, in addition to appearing in that agent's conversation view.

#### Scenario: Chatbot turn is ingested
- **WHEN** the reference chatbot answers a user message
- **THEN** a turn with one LLM span, its input and output, is streamed to the platform and appears in that agent's conversation view

#### Scenario: The chatbot's span is a real OpenTelemetry span
- **WHEN** the reference chatbot answers a user message
- **THEN** the resulting span is emitted via OpenTelemetry (not the platform's custom span-event
  type) and is visible as a trace in the platform's own frontend and in Grafana, correlated to the
  turn by its `trace_id`

### Requirement: A reference multi-step reasoning agent is provided
The system SHALL ship a runnable reasoning agent that answers a problem through more than one LLM
call within a single turn (for example, classifying, planning, solving and verifying), sending
each call as its own span under that turn. Each call SHALL be routed through the shared LLM
gateway (`agent-llm-gateway`) by a task-scoped model group name rather than a hardcoded provider
endpoint, so that calls serving different purposes within the same turn MAY be answered by
different models. When a fallback model group is configured for a call's task, the agent SHALL
name it on the underlying request so a failed primary deployment does not fail the turn when a
working fallback is available. The agent SHALL learn its own task-scoped model group names by
discovering its registration from the platform at startup, rather than requiring an operator to
know and pass them by hand, unless an explicit override is given or discovery itself fails. Each
of this agent's spans SHALL be a real OpenTelemetry span using the OpenTelemetry GenAI semantic
conventions for the model, token usage and (when known) cost it recorded, rather than the
platform's custom span-event type.

#### Scenario: Reasoning turn has multiple spans
- **WHEN** the reference reasoning agent answers one problem using several internal LLM calls
- **THEN** the resulting turn contains one span per internal call, in order, under a single turn
  with one final output

#### Scenario: Reasoning agent can replay a suite with expected answers
- **WHEN** the reference reasoning agent is run against cases from an existing test suite that
  specify an expected answer
- **THEN** each resulting turn's start event carries that expected answer as its reference

#### Scenario: Plan and verify calls use the reasoning-scoped model group
- **WHEN** the reference reasoning agent performs its planning or verification call for a turn
- **THEN** that call is addressed to the agent's own discovered (or explicitly overridden)
  reasoning-scoped model group, and the resulting span records the concrete model the gateway
  actually used, not the group name

#### Scenario: The solve call uses the generation-scoped model group
- **WHEN** the reference reasoning agent performs its solving call for a turn
- **THEN** that call is addressed to the agent's own discovered (or explicitly overridden)
  generation-scoped model group, and the resulting span records the concrete model the gateway
  actually used, not the group name

#### Scenario: A gateway failure does not silently fall back to a direct provider call
- **WHEN** the shared gateway is unreachable during one of the reasoning agent's calls
- **THEN** that call fails visibly (surfaced the same way any other call failure is handled today)
  rather than the agent silently calling a provider directly, bypassing the gateway

#### Scenario: A configured fallback keeps a turn alive when the primary group fails
- **WHEN** a fallback model group is configured for the reasoning, generation, or classification
  task and the primary deployment for that task fails
- **THEN** the agent's call succeeds against the fallback group, and the resulting span records
  the concrete model that actually answered

#### Scenario: The agent discovers its own model group names at startup
- **WHEN** the reference reasoning agent starts without an explicit model-group override and
  successfully reads its own registration from the platform
- **THEN** it addresses its reasoning, generation, and classification calls to the group names the
  platform computed for this agent's own registered name, not the hardcoded dev-default names,
  even when this agent is registered under a different name

#### Scenario: An explicit override always wins over discovery
- **WHEN** the reference reasoning agent is started with an explicit model-group flag
- **THEN** that explicit group name is used for the matching call regardless of what discovery
  would have returned, and discovery's result for that task is not consulted

#### Scenario: A failed discovery falls back to the hardcoded defaults, visibly
- **WHEN** the reference reasoning agent cannot reach the platform's self-discovery endpoint (or
  its token is rejected) and no explicit model-group override was given
- **THEN** the agent starts anyway, uses the hardcoded default group names, and logs a visible
  warning that discovery failed and defaults are in use

#### Scenario: A classification call precedes planning, using a third task-scoped model group
- **WHEN** the reference reasoning agent begins answering a problem
- **THEN** it first makes a classification call addressed to its own discovered (or explicitly
  overridden) classification-scoped model group, recorded as its own span, before the planning
  call begins - using the same gateway-routed calling mechanism the other three calls already use,
  never a direct, ungated call to a classification LLM

#### Scenario: A third task type does not disturb the first two
- **WHEN** the reasoning agent's classification call is added ahead of planning
- **THEN** the planning, solving and verification calls continue to use their existing
  reasoning-scoped and generation-scoped groups unchanged

#### Scenario: All four calls produce real OpenTelemetry spans under one trace
- **WHEN** the reference reasoning agent answers one problem through its classify, plan, solve and
  verify calls
- **THEN** all four spans are emitted via OpenTelemetry under the turn's single trace, each
  carrying its own model, token usage and cost attributes, viewable as one connected trace in
  Tempo/Grafana and in the platform's own frontend

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
directly under any circumstance. Its model-call and tool-call spans SHALL be real OpenTelemetry
spans, the model-call span using the OpenTelemetry GenAI semantic conventions, exactly like the
platform's other reference agents.

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

#### Scenario: The external classification call is still traced
- **WHEN** the agent calls the external, non-LLM classification service
- **THEN** that call is recorded as a real OpenTelemetry `tool`-kind span under the turn's trace,
  even though it is not subject to the gateway-only constraint and carries no GenAI model
  attributes
