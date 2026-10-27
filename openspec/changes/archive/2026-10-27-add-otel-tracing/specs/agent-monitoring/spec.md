# Spec Delta

## MODIFIED Requirements

### Requirement: Conversation and turn drill-down
The system SHALL let the user browse an agent's sessions and open any turn to see its full input,
output, and every evaluator's score, criteria and reasons for that turn, from the platform's own
stored data. When the turn has a `trace_id`, the system SHALL also show its full span tree
(including every intermediate model or tool call, each with its duration and, for a model call,
its tokens and computed cost), fetched live from Tempo (`trace-observability`); this span-tree
section SHALL be the only part of the drill-down affected when Tempo is unreachable or the turn
has no `trace_id`.

#### Scenario: Multi-span turn is fully visible
- **WHEN** the user opens a turn that involved more than one model or tool call and has a
  `trace_id`
- **THEN** each call is shown in order with its own timing and content, alongside the turn's final
  output

#### Scenario: Per-evaluator breakdown
- **WHEN** the user opens an evaluated turn that was scored by more than one evaluator
- **THEN** each evaluator's score, per-criterion scores and reasons are listed individually, together with the combined score

#### Scenario: Trace unavailable does not hide the rest of the turn
- **WHEN** the user opens a turn whose `trace_id` cannot currently be resolved (Tempo is
  unreachable, or the turn predates this capability and has no `trace_id`)
- **THEN** the turn's input, output and evaluator scores are shown normally, and only the span-tree
  section shows that no trace is available
