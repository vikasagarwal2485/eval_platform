# Spec Delta

## Purpose

Gives both evaluation surfaces - the benchmark Runner and live agents - a real distributed trace of
each request's full call tree (agent start, reasoning, tool calls, model calls, generation),
stored in Grafana Tempo via OpenTelemetry and viewable both in the platform's own frontend and in
Grafana, with a computed cost figure alongside the existing latency/token metrics. Evaluation
itself never depends on Tempo being reachable - only viewing the detailed tree does.

## ADDED Requirements

### Requirement: A self-contained observability stack is available
The system SHALL provide an OpenTelemetry Collector, Grafana Tempo, and Grafana, deployable as a
self-contained stack independent of the main backend's own deployment, the same way the LLM
gateway (`agent-llm-gateway`) is a self-contained stack independent of the main backend.

#### Scenario: Stack starts independently
- **WHEN** the observability stack is started
- **THEN** it runs without requiring the main backend, the Runner, or any agent to be running, and
  without requiring any change to how those are started

#### Scenario: Main backend starts without the stack
- **WHEN** the observability stack is not running
- **THEN** the main backend, the Runner, and agent ingest all continue to function; only the
  trace-tree view (not evaluation, not scoring, not any other feature) is affected

### Requirement: A trace correlates to the request or turn it describes
Every benchmark `Result` and every agent turn that produced OpenTelemetry spans SHALL record the
`trace_id` of its trace, so the platform can look up that specific trace later without searching.

#### Scenario: A result names its trace
- **WHEN** a benchmark request completes and emitted OpenTelemetry spans
- **THEN** its `Result` row records the `trace_id` those spans were emitted under

#### Scenario: A turn names its trace
- **WHEN** an agent turn's model/tool calls were emitted as OpenTelemetry spans
- **THEN** the turn's summary (sent via the existing lightweight ingest) records that `trace_id`

#### Scenario: A pre-existing record has no trace
- **WHEN** the platform shows a `Result` or turn recorded before this capability existed
- **THEN** it has no `trace_id`, and the frontend shows that no trace is available for it - the
  same way it would for a trace that Tempo can no longer retain

### Requirement: The frontend renders a structured span tree from Tempo, live
Given a `trace_id`, the system SHALL let the user view that trace's full span tree - every span's
name, kind (for example start, reasoning, tool call, model call, generation), duration, and (for a
model-call span) its token counts and computed cost - inside the platform's own frontend, queried
from Tempo at view time rather than duplicated into the platform's own database.

#### Scenario: Viewing a result's trace
- **WHEN** the user opens a benchmark result that has a `trace_id`
- **THEN** the frontend fetches and displays that trace's span tree, including every phase the
  Runner recorded for that request

#### Scenario: Viewing a turn's trace
- **WHEN** the user opens an agent turn that has a `trace_id`
- **THEN** the frontend fetches and displays that trace's span tree, including every model and
  tool call the agent made for that turn, in the order they occurred

#### Scenario: A span tree shows per-model-call metrics
- **WHEN** a trace's span tree includes a model-call span
- **THEN** that span's view shows its time-to-first-token, input/output token counts, and computed
  cost, alongside its duration

### Requirement: The trace view degrades gracefully when Tempo is unreachable
Tempo's availability SHALL affect only the trace-tree view. No other feature - evaluation,
scoring, sampling, judging, the attention dashboard, or any other part of a result's or turn's own
drill-down - SHALL be affected by Tempo being unreachable.

#### Scenario: Tempo is down while viewing a trace
- **WHEN** the user opens a result or turn that has a `trace_id` while Tempo cannot be reached
- **THEN** the span-tree section shows that traces are temporarily unavailable, and every other
  part of that result's or turn's drill-down (scores, output, metrics) is shown normally

#### Scenario: Tempo is down and does not affect evaluation
- **WHEN** Tempo is unreachable
- **THEN** benchmark runs continue to execute and score normally, and live-agent evaluation
  (sampling, judging, the attention dashboard) continues to run normally

### Requirement: Grafana is available as a second way to view the same traces
The system SHALL make the same traces visible in Grafana (via Tempo as its data source), so a user
who prefers Grafana's own trace view, dashboards, or service graphs is not limited to the
platform's own frontend.

#### Scenario: A trace viewable in the platform's frontend is also viewable in Grafana
- **WHEN** a trace has been exported to Tempo
- **THEN** it can be found and viewed in Grafana by its `trace_id`, independent of whether the
  platform's own frontend is used

### Requirement: Cost is computed from token usage and a maintained price list
The system SHALL compute a cost figure for a model call from its token usage and a per-model,
per-provider price list that the platform maintains, and SHALL record that figure on the
request/turn it belongs to without fabricating a cost when the model or its price is unknown.

#### Scenario: A known model's cost is computed
- **WHEN** a model call completes and its model has a configured price-per-token entry
- **THEN** its cost is computed from its recorded token counts and that entry, and stored alongside
  the request's or turn's other metrics

#### Scenario: An unpriced model records no cost
- **WHEN** a model call completes for a model with no configured price-list entry
- **THEN** no cost figure is fabricated for it - it is recorded as absent, the same way an
  unavailable metric already is elsewhere in the platform
