# Spec Delta

## Purpose

Defines the versioned event contract deployed agents use to stream every LLM interaction into the platform, and guarantees that ingesting it is fast, safe to retry, and never a way for the platform to slow down or break the agent.

## ADDED Requirements

### Requirement: Versioned event batch ingest
The system SHALL accept a batch of events over an authenticated HTTP endpoint identified by a schema version, and SHALL respond without invoking any model.

#### Scenario: Batch accepted
- **WHEN** an agent submits a valid batch of events with its ingest token
- **THEN** the platform stores the events and returns promptly with a count of accepted, duplicate and rejected events, and no model call happens in that request

#### Scenario: Unsupported version rejected
- **WHEN** a batch declares a schema version the platform does not support
- **THEN** the whole batch is rejected with an error naming the unsupported version, and no events from it are stored

#### Scenario: Unauthenticated or unknown token rejected
- **WHEN** a batch is submitted without a valid ingest token
- **THEN** the request is rejected as unauthorized and nothing is stored

### Requirement: Three event types describe a conversation
The system SHALL recognize `turn.start` (the user's input and, optionally, an expected answer), `span` (one LLM or tool call with its timing, and for an LLM call the model identity, messages, output and token usage), and `turn.end` (the turn's final status and output).

#### Scenario: A turn is reconstructed from its events
- **WHEN** an agent sends a `turn.start`, one or more `span` events, and a `turn.end` for the same turn
- **THEN** the platform stores one turn holding that input, output, status and its ordered spans

#### Scenario: Unknown fields are ignored
- **WHEN** an event includes fields the platform's current version does not recognize
- **THEN** the event is still accepted and stored, and the unrecognized fields are ignored

### Requirement: Ingest is idempotent
Turns, sessions and spans SHALL be uniquely identified by an agent-scoped natural key, so that resending the same event never creates a duplicate record.

#### Scenario: Retried batch causes no duplication
- **WHEN** an agent resends a batch it already successfully sent, identified by the same turn, session and span identifiers
- **THEN** no new records are created and the resent events are reported as duplicates, not as an error

### Requirement: Ingest tolerates out-of-order events
The system SHALL accept `span` or `turn.end` events for a turn that has not yet had a `turn.start` recorded, creating the turn implicitly and filling in its input when `turn.start` later arrives.

#### Scenario: Turn.end arrives before turn.start
- **WHEN** a `turn.end` event for a turn arrives before that turn's `turn.start`
- **THEN** the turn is created and marked with its final status immediately, and later receiving the `turn.start` fills in the input without creating a second turn

### Requirement: Malformed events are rejected individually
A batch containing one or more malformed events SHALL have only those events rejected, each reported with its position in the batch and a reason; every well-formed event in the same batch SHALL still be stored.

#### Scenario: One bad event does not fail the batch
- **WHEN** a batch of ten events contains one event missing a required field
- **THEN** the response reports that one event as rejected with its index and reason, and the other nine are stored

### Requirement: Ingest enforces size and content limits
The system SHALL enforce limits on batch size, event count and field length, truncating an oversized text field with a visible marker rather than rejecting the whole event.

#### Scenario: Oversized output is truncated, not dropped
- **WHEN** a span or turn reports output text beyond the configured limit
- **THEN** the stored text is truncated with a marker indicating truncation, and the event is still accepted

#### Scenario: Batch too large is rejected
- **WHEN** a submitted batch exceeds the configured maximum size
- **THEN** the whole request is rejected with a clear error before any of its events are processed

### Requirement: A turn without a closing event is marked abandoned
A turn that has not received a `turn.end` within a configurable timeout SHALL be marked abandoned and SHALL NOT be queued for evaluation.

#### Scenario: Crashed agent leaves an open turn
- **WHEN** a turn's `turn.start` was recorded but no `turn.end` arrives before the abandonment timeout elapses
- **THEN** the turn is marked abandoned and is excluded from evaluation

### Requirement: Model identity on LLM spans drives evaluation eligibility
Each `llm` span SHALL report the model that produced it. A turn whose LLM spans omit a model identity SHALL be recorded but marked as having an unknown model set.

#### Scenario: Model omitted
- **WHEN** an `llm` span is recorded without a model identity
- **THEN** the span and turn are stored, and the turn is flagged so that it is not eligible for automatic evaluation

### Requirement: The agent SDK never blocks or breaks the agent on platform failure
The provided agent SDK SHALL queue events in the agent's process and send them from a background path, and SHALL discard the oldest queued events under sustained backpressure rather than blocking the agent or raising into its code.

#### Scenario: Platform unreachable
- **WHEN** the platform is unreachable while an agent using the SDK is handling a request
- **THEN** the agent's own response to its caller is not delayed or failed because of it, and the SDK retries delivery in the background

#### Scenario: Sustained overload drops oldest events
- **WHEN** events are produced faster than the SDK can deliver them for a sustained period
- **THEN** the oldest queued events are dropped and counted, newer events continue to be queued, and the agent process is never blocked waiting on the queue
