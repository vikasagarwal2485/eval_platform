# Spec Delta

## MODIFIED Requirements

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
