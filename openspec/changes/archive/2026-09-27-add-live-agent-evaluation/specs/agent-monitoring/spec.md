# Spec Delta

## Purpose

Lets a user watch a deployed agent's real traffic and quality as it happens, drill into individual conversations and their evaluations, and spot turns that need attention, without waiting for a benchmark run.

## ADDED Requirements

### Requirement: Agents list shows status and rolling health
The system SHALL show a list of registered agents, each with its liveness status, a rolling quality score, a latency percentile, an error rate and its evaluation backlog size.

#### Scenario: List reflects current state
- **WHEN** the user opens the Agents list
- **THEN** each agent shows its current liveness status and rolling quality, latency, error-rate and backlog figures without needing a manual refresh

### Requirement: Live feed of turns
The agent detail page SHALL show a live-updating feed of turns as they start, finish and get evaluated, each marked with its current state (in progress, evaluation pending, evaluated, or not evaluated with a reason).

#### Scenario: New turn appears without reload
- **WHEN** an agent completes a new turn while its page is open
- **THEN** the turn appears in the live feed without the user reloading the page, first as pending and then updated once evaluated

#### Scenario: Not-evaluated reason is visible
- **WHEN** a turn was not evaluated because no eligible evaluator was available
- **THEN** the feed shows that turn as not evaluated with that reason, distinguishable from a turn still awaiting evaluation

### Requirement: Conversation and turn drill-down
The system SHALL let the user browse an agent's sessions and open any turn to see its full input, output, every span (including intermediate model or tool calls), and every evaluator's score, criteria and reasons for that turn.

#### Scenario: Multi-span turn is fully visible
- **WHEN** the user opens a turn that involved more than one model or tool call
- **THEN** each call is shown in order with its own timing and content, alongside the turn's final output

#### Scenario: Per-evaluator breakdown
- **WHEN** the user opens an evaluated turn that was scored by more than one evaluator
- **THEN** each evaluator's score, per-criterion scores and reasons are listed individually, together with the combined score

### Requirement: Quality and performance over time
The system SHALL provide rolling and time-windowed views of an agent's evaluated quality score, latency percentiles, error rate and token usage, and a chart of quality over time.

#### Scenario: Selecting a window updates the figures
- **WHEN** the user selects a different time window for an agent
- **THEN** the quality, latency, error-rate and token figures and the quality-over-time chart update to reflect only that window

### Requirement: Evaluator strictness is visible
For an agent evaluated by more than one evaluator, the system SHALL show each evaluator's average given score and error count, so a systematically harsher or more lenient evaluator can be identified.

#### Scenario: Two evaluators compared
- **WHEN** an agent has been evaluated by two evaluators over a number of turns
- **THEN** each evaluator's average score and error count are shown side by side

### Requirement: Needs-attention list surfaces low-scoring turns
The system SHALL list evaluated turns scoring below the agent's configured attention threshold, ordered so the user can quickly find and open the worst-scoring recent turns.

#### Scenario: Low-scoring turn is listed
- **WHEN** a turn's evaluated score falls below the agent's attention threshold
- **THEN** it appears in that agent's needs-attention list with enough context to identify it, linking to its full drill-down

### Requirement: Export an agent's turns and evaluations
The system SHALL let the user export an agent's turns and their evaluations, including per-evaluator scores, for a selected time range.

#### Scenario: Export produces evaluation detail
- **WHEN** the user exports an agent's turns for a time range that includes evaluated turns
- **THEN** the export includes each turn's input, output and status alongside its evaluators' scores, criteria and reasons
