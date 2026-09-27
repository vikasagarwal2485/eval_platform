# Spec Delta

## ADDED Requirements

### Requirement: Network latency is disclosed for cloud models
The system SHALL label speed figures of enterprise models as including network transfer and provider queueing, and SHALL show a note wherever local and cloud speeds are compared, stating that they are not like-for-like.

#### Scenario: Leaderboard note
- **WHEN** the leaderboard contains both local and cloud models
- **THEN** it marks cloud models and shows a note that their latency includes network time

#### Scenario: Cloud-only comparison
- **WHEN** all compared models are cloud models
- **THEN** speed figures are shown with the network-time label but no local-vs-cloud caveat

## MODIFIED Requirements

### Requirement: Per-request metrics
The system SHALL record, for every request: total latency, time to first token, time to first answer token (after any thinking output), model load duration, prompt token count, output token count, thinking token count when available, prompt evaluation duration, generation duration, and generation throughput in tokens per second. For enterprise models, token counts SHALL come from the provider's reported usage and timings from client-side measurement, and the source of each figure SHALL be recorded.

#### Scenario: Metrics recorded
- **WHEN** a request completes successfully
- **THEN** all available metrics are stored with the result, sourced from Ollama-reported counters where provided and from wall-clock timing otherwise

#### Scenario: Throughput calculation
- **WHEN** Ollama reports an output token count and a generation duration
- **THEN** tokens per second is output tokens divided by generation duration in seconds

#### Scenario: Metric unavailable
- **WHEN** a metric cannot be obtained for a request (for example the request failed before the first token)
- **THEN** the metric is stored as absent, never as zero, and is excluded from aggregates

#### Scenario: Enterprise request metrics
- **WHEN** an enterprise request completes
- **THEN** latency and time to first token are measured by the client, prompt and output token counts come from the provider's usage report, and load duration and evaluation durations are stored as absent

#### Scenario: Throughput for a cloud request
- **WHEN** an enterprise request reports an output token count
- **THEN** tokens per second is the output tokens divided by the time between the first output token and the end of the stream, and is marked as client-measured

### Requirement: Cold start separated from warm performance
The system SHALL report model load time separately from generation latency, and SHALL exclude load time and warm-up requests from warm-performance aggregates so that model swapping does not distort speed comparisons. Enterprise models have no local load phase: no load duration SHALL be recorded for them, their requests SHALL NOT be flagged cold, and no warm-up request SHALL be sent to them.

#### Scenario: Cold first request
- **WHEN** the first request to a model triggers a model load
- **THEN** the load duration is recorded and shown as cold-start cost, and warm-latency aggregates use the model's warmed requests

#### Scenario: Warm-up disabled
- **WHEN** warm-up is disabled and the first request includes a load
- **THEN** that request is flagged `cold` and excluded from warm aggregates by default, with an option to include it

#### Scenario: Enterprise model has no cold start
- **WHEN** an enterprise model's first request completes
- **THEN** it is not flagged cold and counts in that model's speed statistics

### Requirement: Memory footprint
The system SHALL record the model's resident memory and the portion in GPU/unified memory as reported by Ollama while the model is loaded, when available. Memory footprint does not apply to enterprise models.

#### Scenario: Footprint reported
- **WHEN** Ollama reports that a model is loaded with its memory size
- **THEN** the run stores the size and VRAM/unified-memory share for that model and shows it in the comparison

#### Scenario: Cloud model footprint
- **WHEN** the comparison includes an enterprise model
- **THEN** its memory is shown as not applicable rather than as zero
