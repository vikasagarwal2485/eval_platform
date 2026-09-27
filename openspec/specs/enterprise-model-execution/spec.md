# enterprise-model-execution Specification

## Purpose

Defines how evaluation runs and judging call OpenAI and Anthropic models through their APIs: how models are referenced, how requests and metrics are normalized, how unsupported parameters, reasoning output, rate limits and provider failures are handled.

## Requirements

### Requirement: Call enterprise models through their provider APIs
The evaluation backend SHALL call registered enterprise models through the provider's API for both generation and judging, stream the answer as it is produced, stop the request promptly on cancellation, apply the run's per-request timeout, and return the answer text, reported usage and the model version the provider says it used.

#### Scenario: Generation request
- **WHEN** a run includes an enterprise model and a test case
- **THEN** the backend sends the prompt (with the same instruction suffix used for local models) to the provider and records the streamed answer, token usage and resolved model version

#### Scenario: Cancellation
- **WHEN** the user cancels while an enterprise request is in flight
- **THEN** the request is aborted, no further requests are sent, and results already completed remain

#### Scenario: Timeout
- **WHEN** an enterprise request exceeds the run's per-request timeout
- **THEN** the result is recorded as `error` with a timeout reason and the run continues

### Requirement: Unambiguous model references
Enterprise models SHALL be referenced by a form that cannot collide with an Ollama model name, and existing bare names SHALL continue to refer to Ollama models. The reference SHALL identify both the registered provider and the model id.

#### Scenario: Same-looking names do not collide
- **WHEN** a local model and an enterprise model have similar names
- **THEN** each is selected, run, scored, exported and displayed as a distinct model

#### Scenario: Existing callers unchanged
- **WHEN** a client sends a run request that names only bare Ollama model names
- **THEN** it is handled exactly as before

#### Scenario: Provider and version recorded
- **WHEN** a run with an enterprise model completes
- **THEN** the run records the provider, the model id, and the model version reported by the provider

### Requirement: Map and record run parameters per provider
The backend SHALL apply the run's sampling temperature and maximum output tokens to enterprise requests, and SHALL apply the seed and context-size settings only where the provider supports them. For every enterprise result the system SHALL record which parameters were applied and which were ignored or altered, and why.

#### Scenario: Seed not supported
- **WHEN** a run with a seed includes a model whose provider does not accept one
- **THEN** the request omits it and the result records that the seed was not applied

#### Scenario: Parameter rejected for a reasoning model
- **WHEN** a model does not accept a temperature setting
- **THEN** the request omits or adjusts it as the provider requires and the result records the adjustment

#### Scenario: Visible in results
- **WHEN** the user views a result that had ignored parameters
- **THEN** the drill-down shows them so runs are not presented as more reproducible than they were

### Requirement: Reasoning output from enterprise models
Where an enterprise API reports reasoning tokens the system SHALL record them as thinking tokens, and where it returns a reasoning trace the system SHALL keep it separate from the final answer. Enabling reasoning SHALL apply only to models the user flagged as reasoning models.

#### Scenario: Reasoning tokens reported
- **WHEN** the provider reports reasoning tokens for a request
- **THEN** the result records them as thinking tokens without approximation

#### Scenario: Trace returned
- **WHEN** the provider returns a separate reasoning trace
- **THEN** it is stored as the result's reasoning trace and correctness scoring uses only the final answer

#### Scenario: Toggle only for flagged models
- **WHEN** a model is not flagged as a reasoning model
- **THEN** the run's thinking option is not applied to it

### Requirement: Retry rate limits and transient errors
The backend SHALL retry enterprise requests that fail with rate limiting, provider overload, server errors or connection drops using exponential backoff, honouring the provider's retry hint when given, up to a bounded number of attempts, and SHALL record the number of attempts on the result.

#### Scenario: Rate limited then succeeds
- **WHEN** a provider answers a request with a rate-limit response and then accepts a retry
- **THEN** the result is recorded normally with its attempt count, and the wait time is not counted as generation time

#### Scenario: Retries exhausted
- **WHEN** retries are exhausted
- **THEN** the result is recorded as `error` with the last reason and the run continues

### Requirement: Isolate provider failures to that provider's models
An authentication or authorization failure, or a provider outage that survives retries, SHALL affect only the models of that provider: their remaining requests SHALL be recorded as errors with the reason without being sent, and the run SHALL continue with the other models. Local Ollama unreachability keeps its existing behaviour.

#### Scenario: Authentication failure
- **WHEN** a provider rejects the key on a request
- **THEN** that model's remaining requests are recorded as errors ("authentication failed") without further calls, and other models continue

#### Scenario: Provider outage
- **WHEN** a provider stays unavailable after retries
- **THEN** its remaining requests are recorded as errors, other providers' models still run, and the run completes with those errors visible

#### Scenario: Errors count as failed answers
- **WHEN** an enterprise request ends in error
- **THEN** it is scored and shown like any failed request in the existing scoring rules

### Requirement: Refuse to start runs that cannot call their models
Before starting a run or a re-score, the system SHALL verify that every enterprise model it will call, including judges, is registered, enabled, and has its key available, and SHALL refuse to start with an error naming each problem.

#### Scenario: Key missing for a selected model
- **WHEN** a run request includes an enterprise model whose provider key is not available
- **THEN** the request is rejected, naming the model, the provider and the variable, and no run is created

#### Scenario: Disabled or removed model
- **WHEN** a request names a model that is disabled or no longer registered
- **THEN** it is rejected naming the model

#### Scenario: Judge checked too
- **WHEN** the selected single judge is an enterprise model whose key is missing
- **THEN** the request is rejected before any generation starts

### Requirement: No warm-up or unload requests for enterprise models
The backend SHALL NOT send warm-up requests to enterprise models and SHALL NOT attempt to unload them, because they have no local load phase and every request is billable.

#### Scenario: Warm-up enabled in a mixed run
- **WHEN** a run with warm-up enabled includes a local and an enterprise model
- **THEN** the local model is warmed up and the enterprise model receives only the run's measured requests

#### Scenario: Between models
- **WHEN** the run moves from a local model to an enterprise model or the reverse
- **THEN** only local models are unloaded

### Requirement: Structured judge output from enterprise judges
When an enterprise model acts as judge, the backend SHALL request output in the judge's required structure using the provider's structured-output facility where one exists, and SHALL apply the same parsing, single retry and error handling used for local judges.

#### Scenario: Valid structured output
- **WHEN** an enterprise judge returns the required structure
- **THEN** its per-criterion scores and reasons are stored like any other judge's

#### Scenario: Invalid output
- **WHEN** an enterprise judge's output cannot be parsed after the retry
- **THEN** the judgement is recorded as `error` without failing the run
