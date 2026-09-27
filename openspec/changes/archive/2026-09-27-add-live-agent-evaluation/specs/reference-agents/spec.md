# Spec Delta

## Purpose

Ships two runnable example agents that exercise the full ingest-to-evaluation loop end to end, so the platform's live-evaluation capability can be demonstrated, tested and adopted as a template without requiring the user to build an agent first.

## ADDED Requirements

### Requirement: A reference chatbot agent is provided
The system SHALL ship a runnable chatbot agent that answers user messages using a configurable local model, sends each exchange as one turn with one LLM span to the platform using the agent SDK, and works against the same test infrastructure the platform's own tests use.

#### Scenario: Chatbot turn is ingested
- **WHEN** the reference chatbot answers a user message
- **THEN** a turn with one LLM span, its input and output, is streamed to the platform and appears in that agent's conversation view

### Requirement: A reference multi-step reasoning agent is provided
The system SHALL ship a runnable reasoning agent that answers a problem through more than one LLM call within a single turn (for example, planning, solving and verifying), sending each call as its own span under that turn.

#### Scenario: Reasoning turn has multiple spans
- **WHEN** the reference reasoning agent answers one problem using several internal LLM calls
- **THEN** the resulting turn contains one span per internal call, in order, under a single turn with one final output

#### Scenario: Reasoning agent can replay a suite with expected answers
- **WHEN** the reference reasoning agent is run against cases from an existing test suite that specify an expected answer
- **THEN** each resulting turn's start event carries that expected answer as its reference

### Requirement: The reference agents demonstrate evaluation by a different model
The reference agents' documented setup SHALL configure at least one evaluator that is not the model the agent uses, so that running them produces evaluated turns without any self-judged score.

#### Scenario: End-to-end demonstration
- **WHEN** a reference agent is registered, configured with an evaluator different from its own model, and run to produce several turns
- **THEN** those turns appear evaluated in the platform with a score from the configured evaluator, and none of them show a self-judged evaluation
