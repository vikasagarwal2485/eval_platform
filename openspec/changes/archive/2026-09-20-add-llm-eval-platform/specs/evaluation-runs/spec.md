# Spec Delta

## Purpose

Orchestrates evaluation runs: executing selected Ollama models against selected test cases with configurable parameters, reporting live progress, and recording everything needed to reproduce and compare the run later.

## ADDED Requirements

### Requirement: Start a run over selected models and cases
The system SHALL start a run from a selection of one or more installed models and one or more test cases (from suites and/or ad-hoc prompts), executing every selected model against every selected case.

#### Scenario: Multi-model run
- **WHEN** the user selects three models and a suite of ten cases and starts a run
- **THEN** the system executes 30 model/case combinations (times the configured repeat count) and records a result for each

#### Scenario: Single-model run
- **WHEN** the user selects one model
- **THEN** the run executes normally and results are shown with absolute scores; comparison views indicate that at least two models are needed for side-by-side comparison

#### Scenario: Nothing selected
- **WHEN** the user attempts to start a run with no model or no test case selected
- **THEN** the system refuses to start and indicates what is missing

### Requirement: Run configuration
The system SHALL allow configuring, per run: sampling temperature, random seed, maximum output tokens, context window size, number of repeats per model/case, whether thinking is enabled for thinking-capable models, an optional warm-up request per model, and the judge model used for judged scoring. Defaults SHALL favour reproducibility (temperature 0 and a fixed seed).

#### Scenario: Defaults applied
- **WHEN** the user starts a run without changing advanced settings
- **THEN** the run uses temperature 0, a fixed seed, one repeat, and a warm-up request per model

#### Scenario: Configuration is recorded
- **WHEN** a run completes
- **THEN** the run record stores the full configuration, the prompts and expected answers used, and each model's name, digest, parameter size, and quantization at run time

### Requirement: Sequential, model-grouped execution
The system SHALL execute requests sequentially and SHALL group execution by model (all cases for one model before moving to the next) to avoid repeated model loading, so that measurements are not disturbed by concurrent requests.

#### Scenario: Grouped ordering
- **WHEN** a run covers models A and B and cases 1..N
- **THEN** all requests for model A complete before any request for model B begins

#### Scenario: One run at a time
- **WHEN** a run is in progress and the user starts another
- **THEN** the second run is queued (or rejected with a clear message) and never executes concurrently with the first

### Requirement: Live progress
The system SHALL stream run progress to the UI, including the current model and case, completed/total counts, and partial results as each request completes.

#### Scenario: Progress updates
- **WHEN** a run is executing
- **THEN** the UI updates without manual refresh to show completed/total requests and newly completed results

#### Scenario: Streaming output preview
- **WHEN** a request is in flight
- **THEN** the UI can display the model's output as it streams

### Requirement: Cancellation
The system SHALL let the user cancel an in-progress run, stopping further requests promptly and keeping results already completed.

#### Scenario: Cancel mid-run
- **WHEN** the user cancels a run after some requests have completed
- **THEN** the in-flight request is aborted, no further requests start, the run is marked `cancelled`, and completed results remain viewable and scorable

### Requirement: Failure isolation
The system SHALL treat a failure of one request (timeout, model error, out-of-memory, server disconnect) as a recorded result for that request and SHALL continue with the remaining requests where possible.

#### Scenario: Single request times out
- **WHEN** one request exceeds the configured per-request timeout
- **THEN** that result is recorded as `error` with the reason, and the run continues with the next request

#### Scenario: Ollama becomes unreachable mid-run
- **WHEN** the Ollama server stops responding during a run
- **THEN** the system retries per policy, and if it remains unreachable marks the run `failed` while preserving completed results

### Requirement: Run history and reproducibility
The system SHALL persist every run and let the user list, open, delete, and re-run a past run with the same configuration.

#### Scenario: Re-run
- **WHEN** the user re-runs a historical run
- **THEN** a new run is created with the same models, cases, and configuration, linked to the original for comparison
