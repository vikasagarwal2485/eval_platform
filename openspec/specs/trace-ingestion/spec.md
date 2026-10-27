# trace-ingestion Specification

## Purpose

Defines the versioned event contract deployed agents use to stream every LLM interaction into the platform, and guarantees that ingesting it is fast, safe to retry, and never a way for the platform to slow down or break the agent.

## Requirements

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
The system SHALL recognize `turn.start` (the user's input and, optionally, an expected answer) and
`turn.end` (the turn's final status, output, an optional reasoning trace, the distinct models
used, prompt/completion token totals, a computed cost figure when available, and the
OpenTelemetry `trace_id` that carries the turn's detailed span tree, when one was emitted). The
third event type this requirement originally recognized, `span` (one LLM or tool call), is
retired: per-call detail SHALL NOT be sent through this ingest contract - it is carried only by
the turn's OpenTelemetry trace (`trace-observability`), so that evaluation never depends on
anything beyond these two lightweight, always-on event types. A turn's reasoning trace, previously
assembled by concatenating retired `span` events' own `thinking` fields, is now reported as one
field directly on `turn.end` instead, so a judge call still sees it rather than only the final
output.

#### Scenario: A turn is reconstructed from its events
- **WHEN** an agent sends a `turn.start` and a `turn.end` for the same turn
- **THEN** the platform stores one turn holding that input, output, reasoning trace, status,
  models used, token totals, cost and trace id

#### Scenario: Unknown fields are ignored
- **WHEN** an event includes fields the platform's current version does not recognize
- **THEN** the event is still accepted and stored, and the unrecognized fields are ignored

#### Scenario: A turn with no trace is still fully evaluable
- **WHEN** a `turn.end` event omits a `trace_id` (no OpenTelemetry spans were emitted for that
  turn, or exporting them failed)
- **THEN** the turn is still stored, sampled and evaluated normally - only its own detailed span
  tree is unavailable, not its evaluation

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
Each `turn.end` event SHALL report the distinct models used by that turn's model calls (previously
derived by aggregating per-call `llm` span events, now reported directly since that event type is
retired). A turn whose `turn.end` reports no models SHALL be recorded but marked as having an
unknown model set.

#### Scenario: Model omitted
- **WHEN** a `turn.end` event is recorded without any models listed
- **THEN** the turn is stored, and it is flagged so that it is not eligible for automatic
  evaluation

#### Scenario: Models reported enable eligibility checks as before
- **WHEN** a `turn.end` event lists the models that produced the turn's answer
- **THEN** evaluator eligibility (a model cannot judge a turn it appears in) is checked against
  that list, exactly as it was checked against span-reported models before this capability existed

### Requirement: The agent SDK never blocks or breaks the agent on platform failure
The provided agent SDK SHALL queue events in the agent's process and send them from a background path, and SHALL discard the oldest queued events under sustained backpressure rather than blocking the agent or raising into its code.

#### Scenario: Platform unreachable
- **WHEN** the platform is unreachable while an agent using the SDK is handling a request
- **THEN** the agent's own response to its caller is not delayed or failed because of it, and the SDK retries delivery in the background

#### Scenario: Sustained overload drops oldest events
- **WHEN** events are produced faster than the SDK can deliver them for a sustained period
- **THEN** the oldest queued events are dropped and counted, newer events continue to be queued, and the agent process is never blocked waiting on the queue
