# Spec Delta

## MODIFIED Requirements

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
