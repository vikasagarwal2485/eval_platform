# reference-agents Specification

## Purpose

Ships two runnable example agents that exercise the full ingest-to-evaluation loop end to end, so the platform's live-evaluation capability can be demonstrated, tested and adopted as a template without requiring the user to build an agent first.

## Requirements

### Requirement: A reference chatbot agent is provided
The system SHALL ship a runnable chatbot agent that answers user messages using a configurable local model, sends each exchange as one turn with one LLM span to the platform using the agent SDK, and works against the same test infrastructure the platform's own tests use.

#### Scenario: Chatbot turn is ingested
- **WHEN** the reference chatbot answers a user message
- **THEN** a turn with one LLM span, its input and output, is streamed to the platform and appears in that agent's conversation view

### Requirement: A reference multi-step reasoning agent is provided
The system SHALL ship a runnable reasoning agent that answers a problem through more than one LLM
call within a single turn (for example, planning, solving and verifying), sending each call as its
own span under that turn. Each call SHALL be routed through the shared LLM gateway
(`agent-llm-gateway`) by a task-scoped model group name rather than a hardcoded provider endpoint,
so that calls serving different purposes within the same turn MAY be answered by different models.
When a fallback model group is configured for a call's task, the agent SHALL name it on the
underlying request so a failed primary deployment does not fail the turn when a working fallback
is available. The agent SHALL learn its own task-scoped model group names by discovering its
registration from the platform at startup, rather than requiring an operator to know and pass them
by hand, unless an explicit override is given or discovery itself fails.

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
- **WHEN** a fallback model group is configured for the reasoning or generation task and the
  primary deployment for that task fails
- **THEN** the agent's call succeeds against the fallback group, and the resulting span records
  the concrete model that actually answered

#### Scenario: The agent discovers its own model group names at startup
- **WHEN** the reference reasoning agent starts without an explicit model-group override and
  successfully reads its own registration from the platform
- **THEN** it addresses its reasoning and generation calls to the group names the platform computed
  for this agent's own registered name, not the hardcoded dev-default names, even when this agent
  is registered under a different name

#### Scenario: An explicit override always wins over discovery
- **WHEN** the reference reasoning agent is started with an explicit model-group flag
- **THEN** that explicit group name is used for the matching call regardless of what discovery
  would have returned, and discovery's result for that task is not consulted

#### Scenario: A failed discovery falls back to the hardcoded defaults, visibly
- **WHEN** the reference reasoning agent cannot reach the platform's self-discovery endpoint (or
  its token is rejected) and no explicit model-group override was given
- **THEN** the agent starts anyway, uses the hardcoded default group names, and logs a visible
  warning that discovery failed and defaults are in use

### Requirement: The reference agents demonstrate evaluation by a different model
The reference agents' documented setup SHALL configure at least one evaluator that is not the model the agent uses, so that running them produces evaluated turns without any self-judged score.

#### Scenario: End-to-end demonstration
- **WHEN** a reference agent is registered, configured with an evaluator different from its own model, and run to produce several turns
- **THEN** those turns appear evaluated in the platform with a score from the configured evaluator, and none of them show a self-judged evaluation
