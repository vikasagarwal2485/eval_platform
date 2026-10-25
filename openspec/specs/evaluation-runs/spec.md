# evaluation-runs Specification

## Purpose

Orchestrates evaluation runs: executing selected Ollama models against selected test cases with configurable parameters, reporting live progress, and recording everything needed to reproduce and compare the run later.

## Requirements

### Requirement: Start a run over selected models and cases
The system SHALL start a run from a selection of one or more available models (installed Ollama models, or enabled enterprise models whose provider key is available) and one or more test cases (from suites and/or ad-hoc prompts), executing every selected model against every selected case.

#### Scenario: Multi-model run
- **WHEN** the user selects three models and a suite of ten cases and starts a run
- **THEN** the system executes 30 model/case combinations (times the configured repeat count) and records a result for each

#### Scenario: Single-model run
- **WHEN** the user selects one model
- **THEN** the run executes normally and results are shown with absolute scores; comparison views indicate that at least two models are needed for side-by-side comparison

#### Scenario: Nothing selected
- **WHEN** the user attempts to start a run with no model or no test case selected
- **THEN** the system refuses to start and indicates what is missing

#### Scenario: Local and enterprise models together
- **WHEN** the user selects one Ollama model and one enterprise model with a suite of ten cases
- **THEN** both models run all ten cases with the same prompts, settings and scoring, and results are compared side by side

#### Scenario: Unavailable model selected
- **WHEN** a run request names a model that is not available (not installed, disabled, or missing its provider key)
- **THEN** the system refuses to start and names the model and the reason

### Requirement: Run configuration
The system SHALL allow configuring, per run: sampling temperature, random seed, maximum output tokens, context window size, number of repeats per model/case, whether thinking is enabled for thinking-capable models, an optional warm-up request per model, and the judging mode and judge model used for judged scoring (which may be any available local or enterprise model). Defaults SHALL favour reproducibility (temperature 0 and a fixed seed). Settings that a model's provider does not support SHALL be recorded as not applied.

#### Scenario: Defaults applied
- **WHEN** the user starts a run without changing advanced settings
- **THEN** the run uses temperature 0, a fixed seed, one repeat, and a warm-up request per model

#### Scenario: Configuration is recorded
- **WHEN** a run completes
- **THEN** the run record stores the full configuration, the prompts and expected answers used, and each model's name, digest, parameter size, and quantization at run time

#### Scenario: Unsupported setting
- **WHEN** a run includes an enterprise model whose provider does not support a configured setting (for example a seed or context size)
- **THEN** the run still executes, and the result records that the setting was not applied

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
The system SHALL treat a failure of one request (timeout, model error, out-of-memory, server disconnect, provider rate limit or authentication failure) as a recorded result for that request and SHALL continue with the remaining requests where possible.

#### Scenario: Single request times out
- **WHEN** one request exceeds the configured per-request timeout
- **THEN** that result is recorded as `error` with the reason, and the run continues with the next request

#### Scenario: Ollama becomes unreachable mid-run
- **WHEN** the Ollama server stops responding during a run
- **THEN** the system retries per policy, and if it remains unreachable marks the run `failed` while preserving completed results

#### Scenario: Provider rate limit
- **WHEN** an enterprise request is rate limited and the retries are exhausted
- **THEN** that result is recorded as `error` with the reason, and the run continues

#### Scenario: Provider authentication failure
- **WHEN** an enterprise provider rejects the key
- **THEN** the remaining requests for that provider's models are recorded as errors without being sent, and the run continues with other models

### Requirement: Run history and reproducibility
The system SHALL persist every run and let the user list, open, delete, and re-run a past run with the same configuration.

#### Scenario: Re-run
- **WHEN** the user re-runs a historical run
- **THEN** a new run is created with the same models, cases, and configuration, linked to the original for comparison

### Requirement: A run can attach one or more skills to every model it evaluates
The system SHALL let the user attach one or more registered skills to a run's configuration. When
one or more skills are attached, every request the run sends - for every selected model, every
selected case, every repeat - SHALL have the attached skills' instructions included in its prompt,
in addition to that case's own prompt and template. A run started with no skills attached SHALL
behave exactly as it already does today. When a model's warm-up request is sent, it SHALL also
include the run's attached skill(s) instructions, so that any one-time cost of processing that
prefix is absorbed by the (already-excluded-from-measurement) warm-up request rather than by the
first measured case.

#### Scenario: A skill's instructions reach every model in the run
- **WHEN** the user attaches a skill to a run that selects two models and ten cases
- **THEN** all twenty requests (times the configured repeat count) include that skill's
  instructions in their prompt, and none of the run's other behavior (sequencing, scoring,
  live progress) changes

#### Scenario: Multiple skills attach together
- **WHEN** the user attaches two skills to a run
- **THEN** every request in that run includes both skills' instructions

#### Scenario: No skills attached is unchanged behavior
- **WHEN** the user starts a run without attaching any skill
- **THEN** every request's prompt is built exactly as it was before this capability existed

#### Scenario: An unknown or removed skill id is rejected at start
- **WHEN** the user attempts to start a run naming a skill id that does not exist
- **THEN** the system refuses to start the run and names the missing skill, the same way an
  unavailable model selection is already refused

#### Scenario: Warm-up carries the skill prefix
- **WHEN** a run has one or more skills attached and warm-up is enabled for a model that supports it
- **THEN** that model's warm-up request includes the attached skill(s) instructions, identically to
  how every measured request for that model will include them

#### Scenario: No skills attached means warm-up is unchanged
- **WHEN** a run has no skills attached
- **THEN** the warm-up request is built exactly as it already is today

### Requirement: A run's attached skills are recorded as they were at run time
The system SHALL store, with the run's configuration, the exact name and instructions of every
skill it attached at the time it started - not merely a reference to the registry entry - so that
editing or deleting a skill afterward never changes what a past run shows it used.

#### Scenario: Editing a skill after a run does not alter that run
- **WHEN** a skill's instructions are edited after a run that attached it has completed
- **THEN** the run's own stored configuration still shows the instructions exactly as they were
  when the run executed

#### Scenario: Deleting a skill after a run does not alter that run
- **WHEN** a skill is deleted after a run that attached it has completed
- **THEN** the run's own record is unaffected and still names the skill and shows the instructions
  it used

#### Scenario: Comparing a skill-equipped run against a bare run
- **WHEN** the user compares a run that attached a skill against a run of the same models and
  suite with no skill attached
- **THEN** the existing run-vs-run comparison shows both runs' quality, latency and tokens-per-sec
  side by side, using the comparison tooling that already exists for comparing any two runs
