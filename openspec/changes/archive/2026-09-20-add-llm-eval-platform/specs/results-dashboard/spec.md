# Spec Delta

## Purpose

Provides the browser interface through which users choose models, enter or select test inputs, launch runs, and view and compare accuracy, reasoning, quality, and performance results.

## ADDED Requirements

### Requirement: Model selection
The web UI SHALL show all installed Ollama models with key details and let the user select multiple models via checkboxes for a run.

#### Scenario: Select multiple models
- **WHEN** the user ticks three models
- **THEN** the UI shows the count of selected models and enables starting a run

#### Scenario: Ollama unreachable
- **WHEN** Ollama is unreachable
- **THEN** the UI shows the connectivity error and disables run creation

### Requirement: Input entry
The web UI SHALL let the user provide inputs either by typing an ad-hoc prompt with a chosen category (classification, reasoning, generation) and optional expected answer, or by selecting one or more test suites/cases.

#### Scenario: Ad-hoc classification prompt
- **WHEN** the user types a prompt, chooses `classification`, lists the allowed labels and the expected label, and submits
- **THEN** the UI creates a single-case run for the selected models

#### Scenario: Choose an existing suite
- **WHEN** the user selects a suite
- **THEN** all its cases are included, with the ability to deselect individual cases before starting

### Requirement: Run launch and live view
The web UI SHALL let the user adjust run configuration, start the run, and watch live progress with the ability to cancel.

#### Scenario: Watch a run
- **WHEN** a run is in progress
- **THEN** the UI shows a progress indicator, the current model and case, and results appearing as they complete

### Requirement: Comparison summary
The web UI SHALL present a leaderboard of the compared models showing per-category scores, composite score, and key performance figures (median latency, tokens per second, time to first token), sortable by any column.

#### Scenario: Sort leaderboard
- **WHEN** the user sorts by tokens per second
- **THEN** the leaderboard reorders accordingly

#### Scenario: Adjust composite weights
- **WHEN** the user changes category weights
- **THEN** composite scores and ranking update immediately without re-running models

### Requirement: Visual comparisons
The web UI SHALL visualize model comparisons with at least: a per-category score comparison chart, a latency/throughput chart, and a quality-versus-speed view that makes the accuracy/performance trade-off visible.

#### Scenario: Quality vs. speed
- **WHEN** the user opens the trade-off view
- **THEN** each model is plotted by score against speed, with identifiable labels, and is not distinguished by color alone

### Requirement: Side-by-side output inspection
The web UI SHALL show each case's prompt, expected answer, and every model's output side by side, with per-model correctness or judge score, judge justification, reasoning trace (collapsible), and metrics.

#### Scenario: Drill down into a case
- **WHEN** the user opens a case in the results
- **THEN** all models' outputs for that case appear side by side with scores and metrics

#### Scenario: Filter to failures
- **WHEN** the user filters to cases a model got wrong
- **THEN** only those cases are shown

### Requirement: Run history and comparison across runs
The web UI SHALL list past runs and let the user open one or select two runs to compare (for example the same model before and after a quantization or settings change).

#### Scenario: Compare two runs
- **WHEN** the user selects two runs
- **THEN** the UI shows score and performance deltas for models and cases present in both

### Requirement: Export results
The web UI SHALL let the user export a run's results (scores, metrics, outputs) as CSV and JSON.

#### Scenario: Export CSV
- **WHEN** the user exports a run as CSV
- **THEN** the file has one row per model/case/repeat with category, score, outcome, and performance columns

### Requirement: Usability and accessibility
The web UI SHALL work at common desktop and laptop widths, show meaningful loading, empty, and error states, and SHALL be keyboard-operable with accessible labels for controls and charts.

#### Scenario: Empty state
- **WHEN** no runs exist yet
- **THEN** the UI explains how to start the first evaluation rather than showing blank panels
