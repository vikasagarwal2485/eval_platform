# Spec Delta

## ADDED Requirements

### Requirement: Each request is traced as it executes
The system SHALL emit an OpenTelemetry trace for each request the Runner sends, with a span for
each phase it actually performs (warm-up when sent, generation, judging when applicable), and
SHALL record that trace's id on the request's own `Result` row.

#### Scenario: A measured request's phases are traced
- **WHEN** a run executes a request for a case
- **THEN** a trace is emitted covering that request's phases, and the resulting `Result` records
  the trace's id

#### Scenario: Tracing failure never fails the run
- **WHEN** the observability stack is unreachable while a run is executing
- **THEN** the run's requests still execute, score and complete normally, and the affected
  `Result` rows simply have no `trace_id`

#### Scenario: A warm-up request's span is distinguishable from a measured request's
- **WHEN** a model's warm-up request is sent before its measured requests
- **THEN** it is traced as its own distinct span, never conflated with a measured request's own
  trace
