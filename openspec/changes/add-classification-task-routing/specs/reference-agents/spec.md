# Spec Delta

## MODIFIED Requirements

### Requirement: A reference multi-step reasoning agent is provided
The system SHALL ship a runnable reasoning agent that answers a problem through more than one LLM
call within a single turn (for example, classifying, planning, solving and verifying), sending
each call as its own span under that turn. Each call SHALL be routed through the shared LLM
gateway (`agent-llm-gateway`) by a task-scoped model group name rather than a hardcoded provider
endpoint, so that calls serving different purposes within the same turn MAY be answered by
different models.

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
- **THEN** that call is addressed to the gateway's `reasoning-agent__reasoning` model group, and
  the resulting span records the concrete model the gateway actually used, not the group name

#### Scenario: The solve call uses the generation-scoped model group
- **WHEN** the reference reasoning agent performs its solving call for a turn
- **THEN** that call is addressed to the gateway's `reasoning-agent__generation` model group, and
  the resulting span records the concrete model the gateway actually used, not the group name

#### Scenario: A gateway failure does not silently fall back to a direct provider call
- **WHEN** the shared gateway is unreachable during one of the reasoning agent's calls
- **THEN** that call fails visibly (surfaced the same way any other call failure is handled today)
  rather than the agent silently calling a provider directly, bypassing the gateway

#### Scenario: A classification call precedes planning, using a third task-scoped model group
- **WHEN** the reference reasoning agent begins answering a problem
- **THEN** it first makes a classification call addressed to the gateway's
  `reasoning-agent__classification` model group, recorded as its own span, before the planning
  call begins

#### Scenario: A third task type does not disturb the first two
- **WHEN** the reasoning agent's classification call is added ahead of planning
- **THEN** the planning, solving and verification calls continue to use their existing
  `reasoning-agent__reasoning` and `reasoning-agent__generation` groups unchanged
