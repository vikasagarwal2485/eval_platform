# Spec Delta

## MODIFIED Requirements

### Requirement: Side-by-side output inspection
The web UI SHALL show each case's prompt, expected answer, and every model's output side by side,
with per-model correctness or judge score, judge justification, reasoning trace (collapsible), and
metrics. When a result has a `trace_id`, the web UI SHALL also offer its full span tree (each
phase the Runner recorded - warm-up when applicable, generation, judging - with duration, tokens
and computed cost), fetched live from Tempo (`trace-observability`); this section alone SHALL be
affected when Tempo is unreachable or the result has no `trace_id`.

#### Scenario: Drill down into a case
- **WHEN** the user opens a case in the results
- **THEN** all models' outputs for that case appear side by side with scores and metrics

#### Scenario: Filter to failures
- **WHEN** the user filters to cases a model got wrong
- **THEN** only those cases are shown

#### Scenario: Viewing a result's span tree
- **WHEN** the user opens a result that has a `trace_id`
- **THEN** its span tree is shown alongside its existing metrics, with each phase's own duration,
  tokens and cost

#### Scenario: Trace unavailable does not hide the rest of the result
- **WHEN** the user opens a result whose `trace_id` cannot currently be resolved (Tempo is
  unreachable, or the result predates this capability and has no `trace_id`)
- **THEN** the result's output, scores and existing metrics are shown normally, and only the
  span-tree section shows that no trace is available
