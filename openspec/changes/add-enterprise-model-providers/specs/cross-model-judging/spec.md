# Spec Delta

## ADDED Requirements

### Requirement: Cross-model judging spans local and enterprise models
Cross-model judging SHALL work across any mix of evaluated local and enterprise models, following the same rule that a model never judges its own answers, and SHALL disclose which providers will receive other models' answers.

#### Scenario: Mixed pair
- **WHEN** one local model and one enterprise model are evaluated with cross-model judging
- **THEN** the enterprise model judges the local model's answers, the local model judges the enterprise model's answers, and neither judges its own

#### Scenario: Disclosure
- **WHEN** cross-model judging includes an enterprise model as judge
- **THEN** Run setup states that the other models' answers will be sent to that provider

#### Scenario: Cost estimate
- **WHEN** the run setup shows the estimated number of judgements
- **THEN** it distinguishes judgements made by enterprise models from those made locally

## MODIFIED Requirements

### Requirement: Judging runs after generation and limits model loading
Cross-model judging SHALL run only after all generation in the run has finished, so it cannot disturb measured latency. Judging work SHALL be grouped by judge model so each judge model is loaded once per scoring pass rather than alternating between models, and only local judge models SHALL be unloaded between groups. Thinking SHALL be disabled for thinking-capable local judges, as for single-judge mode.

#### Scenario: Speed figures unaffected
- **WHEN** a run with cross-model judging completes
- **THEN** every generation request was measured before any judging request started, and judging requests do not appear in the evaluated models' performance figures

#### Scenario: Grouped by judge
- **WHEN** models A and B judge each other's answers
- **THEN** all of A's judgements are made before any of B's judgements begin

#### Scenario: Cancellation while judging
- **WHEN** the user cancels during the judging stage
- **THEN** judging stops promptly, judgements already made are kept, and the run is marked cancelled

#### Scenario: Enterprise judge group
- **WHEN** an enterprise model is one of the judges
- **THEN** its judgements are made as one group like any other judge, and no unload request is sent for it
